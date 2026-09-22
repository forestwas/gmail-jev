import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
MAIN = ROOT / "main.py"
DECISIONS = ROOT / "decisions.jsonl"

BATCH_SIZE = int(os.getenv("MIGRATION_BATCH_SIZE", "100"))
PAUSE_SECONDS = int(os.getenv("MIGRATION_PAUSE_SECONDS", "60"))
MAX_BATCHES = int(os.getenv("MIGRATION_MAX_BATCHES", "50"))


def count_decisions():
    if not DECISIONS.exists():
        return 0

    return sum(
        1
        for line in DECISIONS.read_text().splitlines()
        if line.strip()
    )


def summarize_new_rows(start_index):
    if not DECISIONS.exists():
        return {}

    rows = [
        json.loads(line)
        for line in DECISIONS.read_text().splitlines()
        if line.strip()
    ][start_index:]

    labels = {}

    for row in rows:
        for label in row.get("proposed_labels", []):
            labels[label] = labels.get(label, 0) + 1

    return {
        "processed": len(rows),
        "archived": sum(bool(row.get("archived")) for row in rows),
        "review": sum(
            "98 — Review" in row.get("proposed_labels", [])
            for row in rows
        ),
        "labels": labels,
    }


def main():
    print("Gmail v3 migration runner")
    print("=" * 60)
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Pause: {PAUSE_SECONDS}s")
    print(f"Maximum batches: {MAX_BATCHES}")
    print()

    for batch_number in range(1, MAX_BATCHES + 1):
        before = count_decisions()

        log_path = ROOT / f"migration-run-batch-{batch_number:03}.log"

        env = os.environ.copy()
        env["MAX_RESULTS"] = str(BATCH_SIZE)
        env["DRY_RUN"] = "false"

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Starting batch {batch_number}..."
        )

        with log_path.open("w") as log_file:
            result = subprocess.run(
                [str(PYTHON), str(MAIN)],
                cwd=ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

        after = count_decisions()
        added = after - before

        if result.returncode != 0:
            print()
            print(f"❌ Batch {batch_number} failed.")
            print(f"Log: {log_path.name}")
            print()

            lines = log_path.read_text(
                errors="replace"
            ).splitlines()

            print("\n".join(lines[-80:]))
            sys.exit(result.returncode or 1)

        if added == 0:
            print()
            print("✓ No unprocessed inbox threads remain.")
            print("✓ Migration complete.")
            return

        summary = summarize_new_rows(before)

        print(
            f"✓ Batch {batch_number}: "
            f"{summary['processed']} processed, "
            f"{summary['archived']} archived, "
            f"{summary['review']} review"
        )

        if summary["labels"]:
            label_text = ", ".join(
                f"{name}={count}"
                for name, count in sorted(
                    summary["labels"].items()
                )
            )
            print(f"  {label_text}")

        if added < BATCH_SIZE:
            print()
            print(
                f"Batch returned only {added} thread(s). "
                "Checking once more to confirm completion..."
            )
        else:
            print(
                f"Waiting {PAUSE_SECONDS}s before next batch..."
            )

        time.sleep(PAUSE_SECONDS)

    print()
    print(
        f"Stopped after safety limit of {MAX_BATCHES} batches."
    )
    print(
        "Run the migration runner again if unprocessed mail remains."
    )


if __name__ == "__main__":
    main()
