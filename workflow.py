"""Shared Gmail workflow labels and search queries."""

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


def inbox_excluding_workflow_labels(extra_terms: str = "") -> str:
    """Build an inbox query that skips threads already labeled by this system."""
    parts = ["in:inbox"]
    if extra_terms.strip():
        parts.append(extra_terms.strip())
    parts.extend(f'-label:"{name}"' for name in WORKFLOW_LABELS)
    return " ".join(parts)


DEFAULT_GMAIL_QUERY = inbox_excluding_workflow_labels()
LIVE_QUERY = inbox_excluding_workflow_labels("newer_than:2d")
BACKFILL_QUERY = inbox_excluding_workflow_labels("older_than:1d")

# Legacy / intermediate label names used only by migration_reset.py
LEGACY_WORKFLOW_LABELS = [
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

MIGRATION_RESET_LABELS = WORKFLOW_LABELS + LEGACY_WORKFLOW_LABELS
