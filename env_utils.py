"""Strict boolean environment flag parsing."""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes"}
_FALSE = {"0", "false", "no"}


def env_flag(name: str, default: str = "false") -> bool:
    """Parse a boolean env var; reject typos instead of treating them as false.

    Missing variables use ``default``. Any other value raises ``ValueError``
    so misconfigured safety switches cannot silently open live writes.
    """
    raw = os.getenv(name, default)
    if raw is None:
        value = default.strip().lower()
    else:
        value = raw.strip().lower()

    if value in _TRUE:
        return True
    if value in _FALSE:
        return False

    raise ValueError(
        f"Invalid {name}={raw!r}. Expected true/false, 1/0, or yes/no."
    )
