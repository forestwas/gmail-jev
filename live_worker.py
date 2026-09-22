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

from workflow import LIVE_QUERY, SCOPES, WORKER_LOCK_NAME, WORKFLOW_LABELS

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
MAIN = ROOT / "main.py"

TOKEN = ROOT / "token.json"
STATE = ROOT / "live_history_state.json"
LOCK = ROOT / WORKER_LOCK_NAME
LOG = ROOT / "live.log"
DETAIL = ROOT / "live-detail.log"


def env_flag(name, default="false"):
    return os.getenv(name, default).lower() in {"1", "true", "yes"}


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


def run_main():
    env = os.environ.copy()
    env["GMAIL_QUERY"] = LIVE_QUERY

    result = subprocess.run(
        [PYTHON, str(MAIN)],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )

    with DETAIL.open("a") as f:
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


def process_unprocessed_recent():
    # Under normal conditions this is a few threads.
    # If backlog builds up, process at most 5 x 100 threads.
    for batch in range(1, 6):
        result = run_main()

        if result.returncode != 0:
            log(
                f"Live main.py failed. "
                f"returncode={result.returncode}"
            )
            return False

        if "Inbox is empty." in result.stdout:
            return True

        log(f"Live batch {batch} completed.")

    return True


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
                log(
                    "History ID expired; "
                    "falling back to recent inbox scan."
                )
            else:
                raise

    else:
        log(
            "First live run; creating history starting point."
        )

    ok = process_unprocessed_recent()

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
