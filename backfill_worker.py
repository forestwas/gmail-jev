import fcntl
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
MAIN = ROOT / "main.py"

LOCK = ROOT / ".backfill.lock"
LOG = ROOT / "backfill.log"
DETAIL = ROOT / "backfill-detail.log"

QUERY = (
    'in:inbox older_than:1d '
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


def run():
    env = os.environ.copy()
    env["GMAIL_QUERY"] = QUERY

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

    if result.returncode != 0:
        log(
            f"Backfill failed. returncode={result.returncode}"
        )
        return

    if "Inbox is empty." in result.stdout:
        log("No unprocessed inbox threads older than 1 day remain.")
    else:
        log("Backfill batch of up to 100 threads completed.")


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
