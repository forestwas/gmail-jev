"""Exclusive flock helper shared by live/backfill and migration tools."""

from __future__ import annotations

import fcntl
import sys
from contextlib import contextmanager
from pathlib import Path

from workflow import WORKER_LOCK_NAME


@contextmanager
def exclusive_worker_lock(root: Path, *, exit_on_busy: bool = True):
    """Hold `.worker.lock` non-blocking exclusive.

    Live/backfill workers exit silently when busy (`exit_on_busy=False`
    and the caller returns). Migration tools should fail loudly.
    """
    lock_path = root / WORKER_LOCK_NAME
    lock_path.touch(exist_ok=True)

    with lock_path.open("r+") as lock:
        try:
            fcntl.flock(
                lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            if exit_on_busy:
                print(
                    "Another worker or migration holds .worker.lock; "
                    "stop scheduled workers and retry.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            raise

        yield
