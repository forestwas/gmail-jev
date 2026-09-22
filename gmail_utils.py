"""Small Gmail MIME / header helpers with no network side effects."""

from __future__ import annotations

import base64


def has_calendar_part(payload):
    """Return True when a Gmail MIME tree contains actual calendar data."""
    if not payload:
        return False

    mime_type = (payload.get("mimeType") or "").lower()
    filename = (payload.get("filename") or "").lower()

    if mime_type == "text/calendar" or filename.endswith(".ics"):
        return True

    return any(
        has_calendar_part(part)
        for part in payload.get("parts", [])
    )


def decode_body(payload):
    text_parts = []

    def walk(part):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if mime_type == "text/plain" and data:
            decoded = base64.urlsafe_b64decode(
                data + "=" * (-len(data) % 4)
            ).decode("utf-8", errors="replace")

            text_parts.append(decoded)

        for child in part.get("parts", []):
            walk(child)

    walk(payload)

    return "\n".join(text_parts).strip()


def get_header(message, name):
    headers = message.get("payload", {}).get("headers", [])

    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]

    return ""
