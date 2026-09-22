import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
MAIN = ROOT / "main.py"

TOKEN = ROOT / "token.json"
STATE = ROOT / "live_history_state.json"
LOCK = ROOT / ".live.lock"
LOG = ROOT / "live.log"
DETAIL = ROOT / "live-detail.log"

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

WORKFLOW_LABELS = [
    "01 — Reply",
    "02 — Action Required",
    "03 — Waiting",
    "04 — Clients",
    "05 — Leads",
    "06 — Finance",
    "07 — Calendar",
    "08 — Read Later",
    "09 — System",
    "97 — Other",
    "98 — Review",
]

LIVE_QUERY = (
    'in:inbox newer_than:2d '
    '-label:"01 — Reply" '
    '-label:"02 — Action Required" '
    '-label:"03 — Waiting" '
    '-label:"04 — Clients" '
    '-label:"05 — Leads" '
    '-label:"06 — Finance" '
    '-label:"07 — Calendar" '
    '-label:"08 — Read Later" '
    '-label:"09 — System" '
    '-label:"97 — Other" '
    '-label:"98 — Review"'
)


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
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())

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


def remove_old_workflow_labels(gmail, thread_ids):
    labels = label_map(gmail)

    removable_ids = [
        labels[name]
        for name in WORKFLOW_LABELS
        if name in labels
    ]

    changed = 0

    for thread_id in thread_ids:
        try:
            thread = gmail.users().threads().get(
                userId="me",
                id=thread_id,
                format="minimal",
            ).execute()

            if not thread_is_inbox(thread):
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
            log(f"Thread reset error {thread_id}: {e}")

    return changed


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
    gmail = gmail_service()
    state = load_state()

    # Record the history boundary for this run.
    boundary = gmail.users().getProfile(
        userId="me"
    ).execute()["historyId"]

    previous = state.get("history_id")

    if previous:
        try:
            changed_threads = history_thread_ids(
                gmail,
                previous,
            )

            if changed_threads:
                reset_count = remove_old_workflow_labels(
                    gmail,
                    changed_threads,
                )

                log(
                    f"{len(changed_threads)} threads with new messages; "
                    f"{reset_count} inbox threads re-queued."
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

    # Even if history did not change, retry recent mail that may
    # have failed on a previous pass.
    process_unprocessed_recent()

    state["history_id"] = boundary
    save_state(state)

    log("Live check completed.")


def main():
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
            run()
        except Exception as e:
            log(
                f"FATAL: {type(e).__name__}: {e}"
            )


if __name__ == "__main__":
    main()
