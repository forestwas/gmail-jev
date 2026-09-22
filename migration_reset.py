import json
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / "token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

APPLY = os.getenv("APPLY_MIGRATION_RESET", "false").lower() in {
    "1",
    "true",
    "yes",
}

WORKFLOW_LABEL_NAMES = [
    # Final v3
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

    # Legacy v2
    "02 — Leads",
    "03 — Clients",
    "04 — Finance",
    "05 — Waiting",
    "06 — Read Later",
    "07 — Action Required",
    "08 — Calendar",
    "99 — Processed",

    # Intermediate v3
    "10 — Clients",
    "11 — Leads",
    "12 — Finance",
    "13 — Calendar",
    "14 — Read Later",
    "15 — System",
]


def gmail_service():
    creds = Credentials.from_authorized_user_file(
        str(TOKEN),
        SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def list_thread_ids_for_query(gmail, query):
    ids = set()
    page_token = None

    while True:
        response = gmail.users().threads().list(
            userId="me",
            q=query,
            maxResults=500,
            pageToken=page_token,
        ).execute()

        ids.update(
            thread["id"]
            for thread in response.get("threads", [])
        )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return ids


gmail = gmail_service()

labels = gmail.users().labels().list(
    userId="me"
).execute().get("labels", [])

name_to_id = {
    label["name"]: label["id"]
    for label in labels
}

thread_to_labels = defaultdict(set)
label_counts = {}

print("\nScanning workflow labels...")
print("=" * 72)

for label_name in WORKFLOW_LABEL_NAMES:
    label_id = name_to_id.get(label_name)

    if not label_id:
        print(f"{label_name:<28} MISSING")
        continue

    query = f'in:inbox label:"{label_name}"'

    try:
        thread_ids = list_thread_ids_for_query(
            gmail,
            query,
        )
    except HttpError as exc:
        if exc.resp.status == 403:
            print("Gmail quota reached. Wait ~60 seconds and run again.")
        raise

    label_counts[label_name] = len(thread_ids)

    for thread_id in thread_ids:
        thread_to_labels[thread_id].add(label_name)

    print(
        f"{label_name:<28} "
        f"inbox_threads={len(thread_ids)}"
    )


timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
snapshot_path = ROOT / f"migration_snapshot_{timestamp}.jsonl"

rows = []

for thread_id, label_names in sorted(thread_to_labels.items()):
    rows.append(
        {
            "thread_id": thread_id,
            "workflow_labels_before": sorted(label_names),
        }
    )

with snapshot_path.open("w", encoding="utf-8") as handle:
    for row in rows:
        handle.write(
            json.dumps(row, ensure_ascii=False) + "\n"
        )


print()
print("MIGRATION RESET AUDIT")
print("=" * 72)
print("Mode:", "APPLY" if APPLY else "DRY RUN")
print(
    "Unique inbox threads with workflow labels:",
    len(thread_to_labels),
)

print("\nLabels:")
for label_name in WORKFLOW_LABEL_NAMES:
    if label_name in label_counts:
        print(
            f"  {label_name:<28} "
            f"{label_counts[label_name]}"
        )

print("\nSnapshot:", snapshot_path.name)


if not APPLY:
    print()
    print("✓ Dry run only")
    print("✓ No Gmail labels were changed")
    print("✓ No messages were changed")
    raise SystemExit


print("\nApplying reset...")

for index, (thread_id, label_names) in enumerate(
    thread_to_labels.items(),
    1,
):
    remove_ids = [
        name_to_id[name]
        for name in label_names
        if name in name_to_id
    ]

    for attempt in range(6):
        try:
            gmail.users().threads().modify(
                userId="me",
                id=thread_id,
                body={
                    "removeLabelIds": remove_ids,
                },
            ).execute()
            break
        except HttpError as exc:
            if exc.resp.status not in {403, 429} or attempt == 5:
                raise

            wait_seconds = 2 ** (attempt + 1)
            print(
                f"Quota/rate limit on thread {thread_id}; "
                f"retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    # Deliberately conservative during migration.
    time.sleep(0.30)

    if index % 100 == 0 or index == len(thread_to_labels):
        print(
            f"Reset {index}/{len(thread_to_labels)} threads"
        )


print()
print("✓ Workflow labels removed from targeted inbox threads")
print("✓ INBOX was not removed")
print("✓ Read/unread state was not changed")
print("✓ Star state was not changed")
