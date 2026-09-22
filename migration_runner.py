import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from worker_lock import exclusive_worker_lock


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
MAIN = ROOT / "main.py"
DECISIONS = ROOT / "decisions.jsonl"
VALIDATION = ROOT / "validation.jsonl"


def env_flag(name, default="false"):
    return os.getenv(name, default).lower() in {"1", "true", "yes"}


def count_rows(path):
    if not path.exists():
        return 0

    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def count_decisions():
    return count_rows(DECISIONS)


def summarize_new_rows(path, start_index):
    if not path.exists():
        return {}

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][start_index:]

    labels = {}

    for row in rows:
        for label in row.get("proposed_labels", []):
            labels[label] = labels.get(label, 0) + 1

    return {
        "processed": len(rows),
        "archived": sum(bool(row.get("archived")) for row in rows),
        "would_archive": sum(
            bool(row.get("would_archive", row.get("archived")))
            for row in rows
        ),
        "review": sum(
            "98 — Review" in row.get("proposed_labels", [])
            for row in rows
        ),
        "labels": labels,
    }


def main():
    load_dotenv()

    apply = env_flag("APPLY_MIGRATION", "false")
    batch_size = int(os.getenv("MIGRATION_BATCH_SIZE", "100"))
    pause_seconds = int(os.getenv("MIGRATION_PAUSE_SECONDS", "60"))
    max_batches = int(os.getenv("MIGRATION_MAX_BATCHES", "50"))

    print("Gmail v3 migration runner")
    print("=" * 60)
    print(f"Batch size: {batch_size}")
    print(f"Pause: {pause_seconds}s")
    print(f"Maximum batches: {max_batches}")
    print(
        "Mode:",
        "APPLY (live Gmail writes)" if apply else "DRY RUN (no Gmail writes)",
    )
    print()

    if not apply:
        print(
            "Refusing live writes. Re-run with APPLY_MIGRATION=true "
            "after you have reviewed a dry-run."
        )
        print(
            "Dry-run runs a single batch only (Gmail labels are unchanged, "
            "so the same threads would otherwise repeat forever)."
        )

    log_path_for_summary = VALIDATION if not apply else DECISIONS

    for batch_number in range(1, max_batches + 1):
        before = count_rows(log_path_for_summary)

        log_path = ROOT / f"migration-run-batch-{batch_number:03}.log"

        env = os.environ.copy()
        env["MAX_RESULTS"] = str(batch_size)
        # Explicit opt-in mirrors migration_reset.py's APPLY_MIGRATION_RESET.
        env["DRY_RUN"] = "false" if apply else "true"

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Starting batch {batch_number}..."
        )

        with log_path.open("w", encoding="utf-8") as log_file:
            result = subprocess.run(
                [str(PYTHON), str(MAIN)],
                cwd=ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=900,
            )

        after = count_rows(log_path_for_summary)
        added = after - before

        if result.returncode != 0:
            print()
            print(f"❌ Batch {batch_number} failed.")
            print(f"Log: {log_path.name}")
            print()

            lines = log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()

            print("\n".join(lines[-80:]))
            sys.exit(result.returncode or 1)

        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        queue_empty = "Inbox is empty." in log_text

        if added == 0 and queue_empty:
            print()
            print("✓ No unprocessed inbox threads remain.")
            print("✓ Migration complete." if apply else "✓ Dry-run complete.")
            return

        if added == 0 and not queue_empty:
            print()
            print(
                "❌ No new decision rows were written, but the inbox query "
                "was not empty. Refusing to mark migration complete."
            )
            print(f"Log: {log_path.name}")
            sys.exit(1)

        summary = summarize_new_rows(log_path_for_summary, before)

        print(
            f"✓ Batch {batch_number}: "
            f"{summary['processed']} processed, "
            f"{summary.get('would_archive', summary['archived'])} "
            f"{'would archive' if not apply else 'archived'}, "
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

        # Dry-run cannot advance the Gmail queue (no labels written), so
        # looping would re-classify the same threads forever.
        if not apply:
            print()
            print(
                "✓ Dry-run sample complete "
                f"({summary['processed']} thread(s) in validation.jsonl)."
            )
            print(
                "Run APPLY_MIGRATION=true python migration_runner.py "
                "to process the live queue in batches."
            )
            return

        if added < batch_size:
            print()
            print(
                f"Batch returned only {added} thread(s). "
                "Checking once more to confirm completion..."
            )
        else:
            print(
                f"Waiting {pause_seconds}s before next batch..."
            )

        time.sleep(pause_seconds)

    print()
    print(
        f"Stopped after safety limit of {max_batches} batches."
    )
    print(
        "Run the migration runner again if unprocessed mail remains."
    )
    sys.exit(1)


if __name__ == "__main__":
    with exclusive_worker_lock(ROOT):
        main()
