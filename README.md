# Gmail + Jev Inbox Triage

Open-source Gmail inbox triage powered by [TypeSafe](https://typesafe.ai) **Jev** (System One). It classifies threads and applies a fixed workflow label taxonomy, optionally archiving mail that does not need a reply or action.

> This repository is a cleaned, shareable version of a private production system. It does **not** include credentials, mailbox data, decision logs, or runtime state.

## What it does

For each matching Gmail thread, `main.py`:

1. Loads thread text (truncated when long)
2. Asks Jev for typed judgments (relationship, message type, reply/action/waiting, archive safety, urgency)
3. Applies one or more workflow labels
4. Optionally removes `INBOX` when the thread is safe to archive
5. Appends a decision row to `decisions.jsonl` (or `validation.jsonl` in dry-run mode)

### Workflow labels

| Label | Meaning |
| --- | --- |
| `01 — Reply` | Human conversation likely needs a written reply |
| `02 — Action Required` | Concrete non-reply action needed |
| `03 — Waiting` | You already acted; waiting on someone else |
| `04 — Clients` | Known or high-confidence client thread |
| `05 — Leads` | Genuine sales / project inquiry |
| `06 — Finance` | Billing, invoices, receipts, insurance, etc. |
| `07 — Calendar` | Real calendar invite / calendar-system event |
| `08 — Read Later` | Newsletters / bulk reading |
| `09 — System` | System, security, or file-share notifications |
| `97 — Other` | Processed, but no useful class matched |
| `98 — Review` | Model was uncertain; needs human review |

## Requirements

- Python 3.11+ (3.12 recommended)
- A Google Cloud project with Gmail API enabled
- OAuth desktop client credentials (`credentials.json`)
- A [TypeSafe API key](https://typesafe.ai)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set TYPESAFE_API_KEY (and optionally MAILBOX_OWNER_NAME)

cp clients.example.json clients.local.json
# edit domains / keywords for your real clients

# Place Google OAuth client secrets next to the scripts:
#   credentials.json
```

First Gmail auth creates `token.json` locally (gitignored).

### Smoke tests

```bash
python jev_test.py      # TypeSafe connectivity
python gmail_test.py    # Gmail OAuth + profile
```

## Usage

### Dry-run classification (recommended first)

```bash
DRY_RUN=true MAX_RESULTS=10 python main.py
```

No Gmail labels are changed. Results go to `validation.jsonl`.

### Apply labels

```bash
DRY_RUN=false python main.py
```

### Continuous workers

| Script | Role |
| --- | --- |
| `live_worker.py` | Recent inbox (`newer_than:2d`); re-queues threads with new messages via Gmail history |
| `backfill_worker.py` | Older unprocessed inbox (`older_than:1d`) |

Both call `main.py` with an appropriate `GMAIL_QUERY` and use file locks so overlapping runs skip safely.

Example launchd / cron: run `live_worker.py` every few minutes and `backfill_worker.py` less often. Keep schedules, logs, and credentials on your machine — do not commit them.

### One-time migration helpers

| Script | Role |
| --- | --- |
| `migration_reset.py` | Audit / optionally strip old workflow labels from inbox threads (dry-run by default) |
| `migration_runner.py` | Batch-process unprocessed inbox until empty |

```bash
# audit only
python migration_reset.py

# apply label removal
APPLY_MIGRATION_RESET=true python migration_reset.py

# process inbox in batches
python migration_runner.py
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | _(required)_ | TypeSafe API access |
| `MAILBOX_OWNER_NAME` | `the mailbox owner` | Name used in Jev prompt framing |
| `DRY_RUN` | `false` | Classify without Gmail writes |
| `MAX_RESULTS` | `100` | Threads per `main.py` run |
| `GMAIL_QUERY` | inbox minus workflow labels | Override search query |
| `KNOWN_CLIENTS_FILE` | `clients.local.json` | Domain/keyword client boosts |
| `GMAIL_RETRY_ATTEMPTS` | `6` | Retries for rate limits / transient errors |

## Security

Never commit:

- `.env`, `credentials.json`, `token.json`, `clients.local.json`
- `*.log`, `*.jsonl`, snapshots, lock files, or mailbox exports

The included `.gitignore` covers these patterns.

## Architecture (short)

```
live_worker / backfill_worker
        │
        ▼
     main.py  ──►  Gmail API (read/modify)
        │
        └──►  TypeSafe Jev (typed judgments)
```

`main.py` is the single classification engine. Workers only choose the query, handle locking/state, and invoke that engine.

## License

[MIT](LICENSE)
