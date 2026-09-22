import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from env_utils import env_flag
from workflow import (
    HISTORY_RECOVERY_QUERY,
    LIVE_QUERY,
    RECOVERY_PROCESS_QUERY,
    SCOPES,
    WORKER_LOCK_NAME,
    WORKFLOW_LABELS,
)

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
MAIN = ROOT / "main.py"

TOKEN = ROOT / "token.json"
STATE = ROOT / "live_history_state.json"
LOCK = ROOT / WORKER_LOCK_NAME
LOG = ROOT / "live.log"
DETAIL = ROOT / "live-detail.log"


def log(msg):
    with LOG.open("a") as f:
        f.write(
            f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n"
        )


def gmail_service():
    creds = Credentials.from_authorized_user_file(
        str(TOKEN),
        SCOPES,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
        except RefreshError as exc:
            raise RuntimeError(
                "Gmail token refresh failed. Re-run gmail_test.py or main.py "
                "to authorize again (Testing OAuth apps expire after ~7 days)."
            ) from exc

    return build("gmail", "v1", credentials=creds)


def load_state():
    if not STATE.exists():
        return {}

    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(data):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STATE)


def label_map(gmail):
    labels = gmail.users().labels().list(
        userId="me"
    ).execute().get("labels", [])

    return {
        x["name"]: x["id"]
        for x in labels
    }


def run_main(gmail_query=LIVE_QUERY):
    env = os.environ.copy()
    env["GMAIL_QUERY"] = gmail_query

    result = subprocess.run(
        [PYTHON, str(MAIN)],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )

    with DETAIL.open("a", encoding="utf-8") as f:
        f.write("\n\n" + "=" * 80 + "\n")
        f.write(datetime.now().isoformat() + "\n")
        f.write(result.stdout)

        if result.stderr:
            f.write("\nSTDERR:\n")
            f.write(result.stderr)

    return result


def history_thread_ids(gmail, start_history_id):
    result = set()
    page_token = None

    while True:
        kwargs = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded"],
            "maxResults": 500,
        }

        if page_token:
            kwargs["pageToken"] = page_token

        response = gmail.users().history().list(
            **kwargs
        ).execute()

        for item in response.get("history", []):
            for added in item.get("messagesAdded", []):
                message = added.get("message", {})
                thread_id = message.get("threadId")

                if thread_id:
                    result.add(thread_id)

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return result


def list_thread_ids_for_query(gmail, query):
    """Paginate every matching thread id once (discovery for recovery)."""
    ids = []
    seen = set()
    page_token = None

    while True:
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": 500,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        response = gmail.users().threads().list(**kwargs).execute()

        for thread in response.get("threads", []):
            thread_id = thread["id"]
            if thread_id in seen:
                continue
            seen.add(thread_id)
            ids.append(thread_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return ids


def thread_is_inbox(thread):
    for message in thread.get("messages", []):
        if "INBOX" in message.get("labelIds", []):
            return True
    return False


def remove_old_workflow_labels(gmail, thread_ids, dry_run):
    labels = label_map(gmail)

    removable_ids = [
        labels[name]
        for name in WORKFLOW_LABELS
        if name in labels
    ]

    changed = 0
    failed = 0

    for thread_id in thread_ids:
        try:
            thread = gmail.users().threads().get(
                userId="me",
                id=thread_id,
                format="minimal",
            ).execute()

            if not thread_is_inbox(thread):
                continue

            if dry_run:
                log(
                    f"DRY_RUN: would re-queue thread {thread_id} "
                    "(remove workflow labels)"
                )
                changed += 1
                continue

            gmail.users().threads().modify(
                userId="me",
                id=thread_id,
                body={
                    "removeLabelIds": removable_ids,
                },
            ).execute()

            changed += 1

        except Exception as e:
            failed += 1
            log(f"Thread reset error {thread_id}: {e}")

    return changed, failed


def process_batches(gmail_query, label="Live", dry_run=False, max_batches=None):
    # Dry-run does not write labels, so the Gmail query never shrinks —
    # run a single sample batch only (same rule as migration_runner).
    if max_batches is None:
        max_batches = 1 if dry_run else 5

    for batch in range(1, max_batches + 1):
        result = run_main(gmail_query)

        if result.returncode != 0:
            log(
                f"{label} main.py failed. "
                f"returncode={result.returncode}"
            )
            return False

        if "Inbox is empty." in result.stdout:
            return True

        log(f"{label} batch {batch} completed.")

        if dry_run:
            log(f"DRY_RUN: stopping after one {label.lower()} batch.")
            return True

    # Safety cap only — do not treat remaining work as success (checkpoint
    # must not advance while the shrinking query still has threads).
    log(
        f"{label} stopped after {max_batches} batch(es) without "
        "emptying the query; refusing success."
    )
    return False


def run_recovery(gmail, dry_run):
    """Re-classify recent inbox once: discover → strip → shrinking batches."""
    if dry_run:
        log(
            "DRY_RUN recovery: single sample batch "
            "(no label strip / no multi-batch loop)."
        )
        return process_batches(
            HISTORY_RECOVERY_QUERY,
            label="Recovery",
            dry_run=True,
        )

    candidate_ids = list_thread_ids_for_query(
        gmail,
        HISTORY_RECOVERY_QUERY,
    )
    log(f"Recovery candidates: {len(candidate_ids)}")

    if not candidate_ids:
        return True

    reset_count, reset_failed = remove_old_workflow_labels(
        gmail,
        candidate_ids,
        dry_run=False,
    )
    log(
        f"Recovery: stripped workflow labels from {reset_count} "
        f"inbox thread(s); failures={reset_failed}."
    )

    if reset_failed:
        return False

    # Success requires the shrinking query to empty; batch count is only a
    # safety cap (independent of MAX_RESULTS).
    return process_batches(
        RECOVERY_PROCESS_QUERY,
        label="Recovery",
        dry_run=False,
        max_batches=50,
    )


def run():
    dry_run = env_flag("DRY_RUN", "true")
    gmail = gmail_service()
    state = load_state()

    # Record the history boundary for this run.
    boundary = gmail.users().getProfile(
        userId="me"
    ).execute()["historyId"]

    previous = state.get("history_id")
    reset_failed = 0
    history_expired = False

    if previous:
        try:
            changed_threads = history_thread_ids(
                gmail,
                previous,
            )

            if changed_threads:
                reset_count, reset_failed = remove_old_workflow_labels(
                    gmail,
                    changed_threads,
                    dry_run=dry_run,
                )

                log(
                    f"{len(changed_threads)} threads with new messages; "
                    f"{reset_count} inbox threads re-queued"
                    f"{' (dry-run)' if dry_run else ''}."
                )

        except HttpError as e:
            # Gmail may return 404 when historyId is too old.
            if e.resp.status == 404:
                history_expired = True
                log(
                    "History ID expired; "
                    "running recent inbox recovery."
                )
            else:
                raise

    else:
        # No prior checkpoint: recent labeled threads with new mail would
        # otherwise be invisible to LIVE_QUERY. Bootstrap via recovery.
        history_expired = True
        log(
            "First live run; running recent inbox recovery before "
            "setting history checkpoint."
        )

    if history_expired:
        ok = run_recovery(gmail, dry_run)
    else:
        ok = process_batches(
            LIVE_QUERY,
            label="Live",
            dry_run=dry_run,
        )

    # Dry-run must not consume production history state.
    if dry_run:
        log("DRY_RUN: history checkpoint not advanced.")
        return ok

    # Only advance the history checkpoint after a successful classify pass
    # and when re-queue mutations did not fail (avoids skipping mail).
    if ok and reset_failed == 0:
        state["history_id"] = boundary
        save_state(state)
        log("Live check completed.")
        return True

    log(
        "Live check incomplete; history checkpoint not advanced."
    )
    return False


def main():
    load_dotenv()
    LOCK.touch(exist_ok=True)

    with LOCK.open("r+") as lock:
        try:
            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            return

        try:
            ok = run()
        except Exception as e:
            log(
                f"FATAL: {type(e).__name__}: {e}"
            )
            raise SystemExit(1) from e

        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
