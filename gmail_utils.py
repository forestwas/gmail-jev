"""Small Gmail MIME / header helpers with no network side effects."""

from __future__ import annotations

import base64
import re


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


def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(
        data + "=" * (-len(data) % 4)
    ).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    text = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>",
        " ",
        html,
    )
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _is_attachment_part(part):
    """Skip named attachments and Content-Disposition: attachment parts."""
    if (part.get("filename") or "").strip():
        return True

    for header in part.get("headers") or []:
        if (header.get("name") or "").lower() != "content-disposition":
            continue
        value = (header.get("value") or "").lower()
        if "attachment" in value:
            return True

    return False


def decode_body(payload):
    """Prefer text/plain; fall back to stripped text/html. Skip attachments."""
    plain_parts = []
    html_parts = []

    def walk(part):
        if _is_attachment_part(part):
            return

        mime_type = (part.get("mimeType") or "").lower()
        body = part.get("body", {})
        data = body.get("data")

        if data:
            decoded = _decode_b64(data)
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)

        for child in part.get("parts", []):
            walk(child)

    walk(payload)

    if plain_parts:
        return "\n".join(plain_parts).strip()

    if html_parts:
        return "\n".join(_html_to_text(html) for html in html_parts).strip()

    return ""


def get_header(message, name):
    headers = message.get("payload", {}).get("headers", [])

    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]

    return ""
