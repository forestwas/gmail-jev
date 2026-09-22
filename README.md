# gmail-jev

Gmail inbox helper built around [TypeSafe](https://typesafe.ai) Jev.

You run it on your own computer. It looks at conversations already in your Gmail account, asks Jev a few structured questions, then puts on labels like Reply, Clients, or Finance. If something looks safe to leave Inbox, it can move it out. Nothing in this repo sends mail for you.

This is the public version of a tool I used privately. Secrets, real mailbox data, and run logs are not included.

## Screenshot

![Gmail with numbered workflow labels](docs/inbox-preview.png)

Same labels show up in the left sidebar and as colored chips on each row. One conversation can have more than one label.

## Pick a setup path

| You | Go here |
| --- | --- |
| Okay with Terminal + Google Cloud yourself | [Path A](#path-a-do-it-yourself) |
| Prefer ChatGPT / Claude / Cursor to walk you through it | [Path B](#path-b-use-an-ai-tool-simple-english) |
| Want to change rules later | [Customize](#customize) |
| Old labels to clean up | [Migration](#migration) |

You only need one path.

**Before you start:** mail can hold private stuff (money, work, personal life). This app uses *your* Google login and *your* TypeSafe key. It can change labels and take mail out of Inbox. Try dry-run first. You are responsible for how you use it.

---

## What you need

| Thing | Where | Local file |
| --- | --- | --- |
| TypeSafe key | [typesafe.ai](https://typesafe.ai) | `.env` → `TYPESAFE_API_KEY` |
| Google Cloud project + Gmail API on | [console.cloud.google.com](https://console.cloud.google.com/) | - |
| OAuth “Desktop” client | Credentials → OAuth client ID → Desktop | `credentials.json` |
| Your Gmail account | Browser login the first time | `token.json` (created for you) |

Software: Python 3.11+ (3.12 is fine), then `pip install -r requirements.txt`.

Optional: `clients.local.json` (copy from `clients.example.json`) so known client domains/keywords get a Clients label boost. Optional: `MAILBOX_OWNER_NAME=Alex` in `.env`.

---

## Path A: do it yourself

1. Read [What you need](#what-you-need).
2. Use the [checklist](#checklist) and [step by step](#step-by-step).
3. First run with dry-run ([below](#try-a-dry-run-first)).
4. Only then turn writes on.
5. Optional: [workers](#keep-it-running).

Don’t put keys into git or into a public chat. See [Privacy notes](#privacy-notes).

---

## Path B: use an AI tool (simple English)

This path is for people who do **not** want to learn coding.

You need:

- This project link: https://github.com/forestwas/gmail-jev  
- An AI tool you already use (ChatGPT, Claude, Cursor, Gemini, etc.)  
- A normal web browser  
- Your own computer (Mac or Windows)

The AI tool will tell you what to click and what to type. **You** still create the TypeSafe key and the Google login file in the browser. **You** decide when Gmail may change.

### Try this first (often enough)

With most popular AI tools, you can open a new chat and paste something like:

```text
I want to use the project at https://github.com/forestwas/gmail-jev
I do not have enough technical knowledge. Guide me step by step.
```

For many people, that alone is enough: the tool will ask questions and tell you what to do in a simple way.

If that does **not** work well, use the detailed steps below one by one.

Below, each step says **where** you are, **what to paste** into the AI tool, and **what you do**.

### Step 1 — Start a chat with your AI tool

1. Open your AI tool (website or app).  
2. Start a **new chat**.  
3. Copy-paste this message:

```text
I want to install this project on my computer:
https://github.com/forestwas/gmail-jev

I am not a programmer. Guide me one small step at a time.
My computer is: [Mac / Windows]   ← write one

Rules:
- Do not put secrets into git
- Do not ask me to paste my API key or my emails into this chat
- Keep DRY_RUN=true until I clearly say I want real Gmail changes
- First runs: only 5 conversations
- Before each command, explain in one short plain sentence what it does
```

The AI tool should then check Python and get the project onto your machine.

**About downloading the project:** many AI tools (especially Cursor) can open or download the GitHub link themselves. If yours can, let it. If it only gives you a command, run that command. You do not need to understand “clone.”

### Step 2 — Install Python (only if the AI tool says you need it)

Stay in the **same chat**. If the AI tool says Python is missing, ask:

```text
Python is missing or too old. Tell me the exact clicks or commands
for my computer ([Mac / Windows]) to install Python 3.11 or newer.
One step at a time.
```

Do what it says, then reply: `Done.`

### Step 3 — Project folder on your computer

If the AI tool has not already downloaded the project, paste:

```text
Put the gmail-jev project on my computer now.
If you can download it from GitHub yourself, do that.
If not, give me one copy-paste command and tell me where the folder will be.
```

When finished, you should have a folder named something like `gmail-jev` on your computer. Remember that folder path (the AI tool should tell you).

### Step 4 — TypeSafe account and API key (you do this in the browser)

The project needs a TypeSafe key so Jev can run.

1. Open this page in your browser: [https://typesafe.ai](https://typesafe.ai)  
2. Create an account / sign in (use the buttons on that site).  
3. Open the API keys page: [https://console.typesafe.ai/keys](https://console.typesafe.ai/keys)  
   - If the site menu looks different, look for **API keys** or **Keys** after you sign in to the console.  
4. Create a new key. Copy it once (it looks like a long secret string). Treat it like a password.  
5. Go back to your AI chat and paste:

```text
I have a TypeSafe API key on my clipboard.
In the gmail-jev folder, create .env from .env.example.
I will type TYPESAFE_API_KEY into .env myself.
Do not ask me to paste the key into this chat.
Also set DRY_RUN=true and MAILBOX_OWNER_NAME to my first name.
```

Then open `.env` on your computer (the AI tool can open it in Cursor, or tell you how to open it in a text editor). Put your key after `TYPESAFE_API_KEY=` with **no spaces**. Save the file.

If TypeSafe asks you to join a waitlist before keys work, finish that first, then come back to this step.

### Step 5 — Google login file for Gmail (you do this in the browser)

You need a file called `credentials.json` next to the project files. Paste this into the AI chat so it can guide clicks, then do the clicks yourself:

```text
I need Google Desktop OAuth credentials for Gmail for gmail-jev.
Guide me click by click. I will do the browser steps.
Cover:
1) open https://console.cloud.google.com/ and create/select a project
2) enable Gmail API
3) OAuth consent screen (Testing; add my Google account as test user)
4) create OAuth client ID type Desktop app
5) download the JSON and save it as credentials.json inside my gmail-jev folder
Remind me: Testing access often expires after about 7 days.
```

When done, `credentials.json` must sit in the same folder as `main.py`.

### Step 6 — Install project packages

Paste:

```text
Inside the gmail-jev folder, create a Python virtual environment
and install requirements.txt.
Give me the exact commands for [Mac / Windows], one at a time.
```

Run what it gives you. Reply `Done` after each step if it asks.

### Step 7 — Small tests + Google permission window

Paste:

```text
Run the small tests: jev_test.py then gmail_test.py.
Explain each in one sentence first.
A browser window may ask me to allow Gmail access — that is normal.
I will approve my own account.
```

When the browser asks, choose your Gmail account and allow access. After this, a `token.json` file should appear in the project folder (keep it private).

### Step 8 — Practice mode (no Gmail label changes)

Paste:

```text
Run main.py in practice mode on 5 conversations:
DRY_RUN=true MAX_RESULTS=5
Then open validation.jsonl and explain the suggested labels in simple English.
Do not turn DRY_RUN off.
```

Check that Gmail labels did **not** change. If something looks wrong, stay in practice mode and ask the AI tool to help.

### Step 9 — Real labels (only when you are ready)

Paste:

```text
I reviewed the practice results. I accept that labels may change in my Gmail.
Give the safest small live command:
DRY_RUN=false MAX_RESULTS=10
Explain what will change before I run it. Wait for my OK.
```

Only run it after you understand the explanation.

### Step 10 — Optional: run automatically later

Paste when you want:

```text
Help me schedule live_worker.py and backfill_worker.py on my computer
using the examples in the README. Keep secrets in .env. One step at a time.
```

### If you get stuck

Paste the error text (hide any keys) and:

```text
Here is the error. Fix it one step at a time. Keep DRY_RUN=true.
```

When Path B works, you can ignore the long DIY pages, or keep using the same AI chat for [workers](#keep-it-running) and [customize](#customize).

---

## Checklist

Handy for Path A. Path B people can tick the same boxes with their AI tool.

1. [ ] Clone repo, make `.venv`, `pip install -r requirements.txt`
2. [ ] TypeSafe key in `.env`
3. [ ] Gmail API + Desktop OAuth → `credentials.json`
4. [ ] Optional `clients.local.json`
5. [ ] `python jev_test.py` and `python gmail_test.py`
6. [ ] `DRY_RUN=true MAX_RESULTS=10 python main.py`
7. [ ] Check `validation.jsonl`
8. [ ] `DRY_RUN=false` when you are ready
9. [ ] Optional workers

---

## Step by step

### Get the code

```bash
git clone https://github.com/forestwas/gmail-jev.git
cd gmail-jev
```

### Python env

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Or: `pip install -e .`

### TypeSafe key

1. Account + key on [typesafe.ai](https://typesafe.ai).
2. Keep the key private.

```bash
cp .env.example .env
```

Example `.env`:

```env
TYPESAFE_API_KEY=your_key_here
MAILBOX_OWNER_NAME=Alex
DRY_RUN=true
MAX_RESULTS=100
```

### Google Cloud

Once per project / mailbox:

1. [Google Cloud Console](https://console.cloud.google.com/) → new or existing project.
2. APIs & Services → Library → enable **Gmail API**.
3. OAuth consent screen. External is common for a personal Gmail. Add yourself as a test user while status is Testing.
4. **Heads-up:** in Testing, Google often expires the grant after about **7 days**. Workers stop until you log in again (`python gmail_test.py` or `main.py`). For always-on setups, publish the app or plan to re-login.
5. Credentials → Create credentials → OAuth client ID → **Desktop app** → download JSON.
6. Save it in the project folder as `credentials.json`.

Scope used:

```text
https://www.googleapis.com/auth/gmail.modify
```

This project’s code only labels and (optionally) takes mail out of Inbox. It does not send mail. Google’s docs for that scope are wider (they also mention compose/send), so treat `token.json` like a password.

### Known clients (optional)

```bash
cp clients.example.json clients.local.json
```

```json
{
  "clients": [
    {
      "name": "Acme",
      "domains": ["acme.com"],
      "keywords": ["Project Nova"]
    }
  ]
}
```

Domains match From/To/Cc addresses. Keywords match subject/body. A hit pushes toward `04 — Clients`.

### Smoke tests

```bash
python jev_test.py
python gmail_test.py
```

`gmail_test.py` opens a browser, then writes `token.json` (gitignored).

### Unit tests (offline)

```bash
python -m unittest discover -v
```

---

## Try a dry-run first

Dry-run suggests labels and writes `validation.jsonl`. It should not change Gmail.

```bash
DRY_RUN=true MAX_RESULTS=10 python main.py
```

Code default is also dry-run if the env var is missing. Check a few lines in `validation.jsonl` before going live.

## Turn on real labeling

```bash
DRY_RUN=false MAX_RESULTS=50 python main.py
```

Then Gmail may get new labels, applied labels, and some Inbox removals. Results go to `decisions.jsonl`.

By default it only picks Inbox conversations that do not already have these workflow labels.

---

## Keep it running

| Script | What it does |
| --- | --- |
| `live_worker.py` | Last day of Inbox (`newer_than:1d`). Re-queues threads that got a new message. |
| `backfill_worker.py` | Older unlabeled Inbox (`older_than:1d`), one batch per run. |

Both call `main.py`, share `.worker.lock`, and exit with an error code if something fails.

Workers need `fcntl` (macOS/Linux). Plain `main.py` is fine on Windows; the schedulers are not.

Example: live every few minutes, backfill once an hour.

Wrappers (copy to repo root):

```bash
cp scripts/run_live.sh.example run_live.sh
cp scripts/run_backfill.sh.example run_backfill.sh
chmod +x run_live.sh run_backfill.sh
```

cron:

```cron
*/5 * * * *  /path/to/gmail-jev/run_live.sh
0 * * * *    /path/to/gmail-jev/run_backfill.sh
```

launchd (macOS): point `ProgramArguments` at `run_live.sh`, `StartInterval` 300, working directory = project folder. Prefer loading secrets from `.env` via the wrapper, not hardcoding them in the plist.

---

## Labels

Numbers keep them sorted in Gmail.

| Label | Meaning |
| --- | --- |
| `01 — Reply` | Someone likely expects a reply |
| `02 — Action Required` | You need to do something other than reply |
| `03 — Waiting` | Ball is in their court |
| `04 — Clients` | Known or likely client work |
| `05 — Leads` | Real sales / project inquiry |
| `06 — Finance` | Bills, receipts, insurance, etc. |
| `07 — Calendar` | Real invite / calendar event (or `.ics` on the latest message) |
| `08 — Read Later` | Newsletters / bulk reading |
| `09 — System` | System / security / file-share noise |
| `97 — Other` | Processed, no useful bucket |
| `98 — Review` | Model was unsure |

Colors are set in Gmail’s UI. The scripts only create names.

---

## How it works (short)

```
worker or main.py
      |
      v
   main.py  -->  Gmail (fetch + label)
      |
      +------>  TypeSafe Jev (structured answers)
      |
      v
  routing.py (thresholds -> label names)
```

Jev answers things like relationship, message type, reply/action/waiting/archive. `routing.py` turns that into labels. If the **latest** message has calendar MIME / `.ics`, type is forced to calendar.

---

## Customize

**Rename labels:** edit `WORKFLOW_LABELS` in `workflow.py` and the same strings in `routing.py`. Update prompts in `main.py` if needed. Names must match Gmail exactly (including the special dash character).

**Colors:** Gmail settings only.

**Thresholds:** `routing.py` (`MESSAGE_TYPE_THRESHOLDS`, reply/action/waiting cutoffs, archive rules). Then `python -m unittest discover -v`.

**Questions Jev gets:** `build_jev_questions()` in `main.py`. Set `MAILBOX_OWNER_NAME` so prompts use your name.

**Which mail:** `GMAIL_QUERY`, or the live/backfill builders in `workflow.py` (`newer_than:1d` / `older_than:1d`). Batch size: `MAX_RESULTS`.

**Clients file:** edit `clients.local.json` anytime.

---

## Config

| Variable | Default | Notes |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | required | TypeSafe |
| `MAILBOX_OWNER_NAME` | `the mailbox owner` | Prompt wording |
| `DRY_RUN` | `true` | No Gmail writes until you set `false` (typos like `tru` abort; only `true`/`false`/`1`/`0`/`yes`/`no`) |
| `MAX_RESULTS` | `100` | Per `main.py` run |
| `GMAIL_QUERY` | inbox minus workflow labels | Override search |
| `KNOWN_CLIENTS_FILE` | `clients.local.json` | Client boosts |
| `GMAIL_RETRY_ATTEMPTS` | `6` | Gmail retries |
| `APPLY_MIGRATION_RESET` | `false` | Live label strip in `migration_reset.py` |
| `APPLY_MIGRATION` | `false` | Live batches in `migration_runner.py` |
| `MIGRATION_BATCH_SIZE` | `100` | |
| `MIGRATION_PAUSE_SECONDS` | `60` | |
| `MIGRATION_MAX_BATCHES` | `50` | |

---

## Files

| File | Role |
| --- | --- |
| `main.py` | Main classifier |
| `routing.py` | Label rules (tested offline) |
| `workflow.py` | Label names + queries |
| `gmail_utils.py` | MIME / headers |
| `live_worker.py` / `backfill_worker.py` | Schedulers |
| `migration_reset.py` / `migration_runner.py` | Cleanup / batch migrate |
| `clients.example.json` | Client template |
| `test_routing.py` | Unit tests |
| `docs/inbox-preview.png` | Screenshot |

---

## Migration

```bash
python migration_reset.py                          # audit only
APPLY_MIGRATION_RESET=true python migration_reset.py

python migration_runner.py                         # dry-run: one sample batch only
APPLY_MIGRATION=true python migration_runner.py    # live writes in batches
```

`migration_runner.py` stays dry-run unless `APPLY_MIGRATION=true`. Dry-run classifies **one** batch into `validation.jsonl` and stops (without labels, the same threads would otherwise repeat forever). If Jev errors out, it fails instead of saying “done.” Keep snapshot/decision files private.

**Stop scheduled live/backfill workers before migration.** Both migration scripts take the same `.worker.lock` as the workers; if a worker is running they exit instead of racing label writes.

---

## Privacy notes

Mail can include passwords, contracts, money stuff, and private talks. You own the risk: protect keys and decide if this tool fits your mailbox.

Classification sends **subject, From/To/Date headers, and message body text** (truncated) to the TypeSafe API, plus your mailbox address for “who is the owner” context. Attachment MIME parts (named files or `Content-Disposition: attachment`) are skipped and not sent to TypeSafe; this code also does not fetch `attachmentId` payloads. Inline body text/html still goes to the model. Google sees the usual Gmail API traffic for listing/modifying threads.

Never commit:

- `.env`, `credentials.json`, `token.json`, `clients.local.json`
- logs, `*.jsonl`, snapshots, locks

`.gitignore` already lists these. Dry-run before large live batches.

### Known limitations

- **History recovery** rechecks Inbox mail from roughly the last **7 days** only (`HISTORY_RECOVERY_QUERY`). If the worker was offline longer than Gmail’s history retention, older gaps may be missed — strip labels / re-run `main.py` on older windows manually. Full-mailbox sync is intentionally not done.
- **First live_worker run** (no `live_history_state.json`) bootstraps with that same recent recovery path before writing a history checkpoint.
- **`live_worker` dry-run** classifies a single batch per invocation (labels are not written, so the query cannot shrink).

---

## FAQ

**Is this a cloud product?**  
No. It runs where you install it.

**Does it send or delete mail?**  
The code does not send mail and does not hard-delete threads. It labels and can remove Inbox. The OAuth scope Google grants is still powerful; keep `token.json` safe. Docs: [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

**What is Jev?**  
TypeSafe’s System One model. It returns structured answers your code can branch on, not a long chat essay. More: [docs.typesafe.ai](https://docs.typesafe.ai/).

**Dry-run changed my labels anyway?**  
With `DRY_RUN=true` (default), `main.py` should skip label writes, and `live_worker.py` only logs would-be re-queues **and does not advance** `live_history_state.json`. Double-check the env on that process, and that you did not set `APPLY_MIGRATION=true`.

**Unverified app warning?**  
Normal in Testing. Add yourself as test user. Grants often last about a week; re-run `gmail_test.py` when they expire.

**Windows?**  
`main.py` yes. Continuous workers **and** migration helpers (`migration_runner.py` / `migration_reset.py`) need macOS/Linux today (they share a `fcntl`-based `.worker.lock`).

**`credentials.json` vs `token.json`?**  
Client app file from Google vs your personal login token after the browser step. Both secret. `gmail_test.py` / `main.py` write `token.json`.

**Quota errors?**  
Lower `MAX_RESULTS`, slow migration pauses, space out workers.

**Nothing gets picked up?**  
Already labeled; query too narrow; live only covers the last day; another process holds `.worker.lock`.

**Reprocess one thread?**  
Strip its workflow labels (or careful `migration_reset.py`), run `main.py` again. Live worker also re-queues when a new message arrives.

**Several Gmail accounts?**  
Separate folders (or separate tokens). Default layout expects files in the project root.

**Rename Clients → Customers?**  
Change strings in `workflow.py` + `routing.py`, migrate Gmail labels. Renaming only in Gmail leaves the old name in code.

**Two labels on one mail?**  
Normal. Context + action can both apply.

**Review empty or huge?**  
Review only when unsure and nothing else matched. Tune prompts/thresholds if the balance feels wrong.

**Known clients vs Jev?**  
Domain/keyword hit forces the Clients path for relationship. Other labels can still apply.

**Bugs?**  
[GitHub issues](https://github.com/forestwas/gmail-jev/issues). Include command + dry-run yes/no + redacted console text. No raw mail bodies or tokens.

**Any production mailbox data here?**  
No. Don’t copy real `.env` / tokens / decision logs into a public fork.

---

## License

[MIT](LICENSE) © Altay Suna
