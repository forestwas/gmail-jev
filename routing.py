"""Pure label-routing decisions (no Gmail / TypeSafe I/O)."""

from __future__ import annotations

import re

MESSAGE_TYPE_THRESHOLDS = {
    "finance": 0.40,
    "calendar": 0.60,
    "newsletter": 0.40,
    "system": 0.40,
    "security": 0.40,
    "file_share": 0.40,
}

_EMAIL_RE = re.compile(
    r"[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)


def _header_domains(participant_headers: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in _EMAIL_RE.finditer(participant_headers or "")
    }


def find_known_client_matches(
    clients: list[dict],
    subject: str,
    thread_text: str,
    participant_headers: str,
) -> list[str]:
    """Match domains against From/To/Cc addresses; keywords against subject/body."""
    domains_in_headers = _header_domains(participant_headers)
    keyword_haystack = "\n".join(
        [
            subject or "",
            thread_text or "",
        ]
    ).lower()

    matches = []

    for client in clients:
        domains = [
            value.strip().lower().lstrip("@")
            for value in client.get("domains", [])
            if value.strip()
        ]
        keywords = [
            value.strip().lower()
            for value in client.get("keywords", [])
            if value.strip()
        ]

        domain_hit = any(domain in domains_in_headers for domain in domains)
        keyword_hit = any(keyword in keyword_haystack for keyword in keywords)

        if domain_hit or keyword_hit:
            matches.append(client.get("name", "Unknown client"))

    return matches


def decide_label_names(
    *,
    known_client_matches: list[str],
    relationship: str,
    relationship_confidence: float,
    message_type: str,
    message_type_confidence: float,
    reply_needed: float,
    action_required: float,
    waiting_on_them: float,
) -> list[str]:
    """Return ordered workflow label names for a classified thread."""
    meaningful: list[str] = []

    if known_client_matches:
        meaningful.append("04 — Clients")
    elif relationship_confidence >= 0.55:
        if relationship == "client":
            meaningful.append("04 — Clients")
        elif relationship == "lead":
            meaningful.append("05 — Leads")

    type_threshold = MESSAGE_TYPE_THRESHOLDS.get(message_type)
    if (
        type_threshold is not None
        and message_type_confidence >= type_threshold
    ):
        if message_type == "finance":
            meaningful.append("06 — Finance")
        elif message_type == "calendar":
            meaningful.append("07 — Calendar")
        elif message_type == "newsletter":
            meaningful.append("08 — Read Later")
        elif message_type in {"system", "security", "file_share"}:
            meaningful.append("09 — System")

    if (
        reply_needed >= 0.50
        and message_type == "human_message"
        and waiting_on_them < 0.70
    ):
        meaningful.append("01 — Reply")

    action_threshold = (
        0.50
        if message_type in {"system", "security", "file_share"}
        else 0.70
    )

    if (
        action_required >= action_threshold
        and message_type != "newsletter"
    ):
        meaningful.append("02 — Action Required")

    if (
        waiting_on_them >= 0.70
        and message_type == "human_message"
        and action_required < 0.70
    ):
        meaningful.append("03 — Waiting")

    uncertain = (
        not known_client_matches
        and relationship_confidence < 0.55
        and message_type_confidence < 0.55
    )

    if uncertain and not meaningful:
        meaningful.append("98 — Review")

    if not meaningful:
        meaningful.append("97 — Other")

    return meaningful


def should_archive_thread(
    *,
    message_type: str,
    message_type_confidence: float,
    can_archive: float,
    reply_needed: float,
    action_required: float,
) -> bool:
    return (
        (
            message_type == "newsletter"
            and message_type_confidence >= 0.65
        )
        or (
            can_archive >= 0.70
            and reply_needed < 0.50
            and action_required < 0.50
        )
    )
