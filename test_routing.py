import base64
import unittest

from gmail_utils import decode_body, get_header, has_calendar_part
from routing import (
    decide_label_names,
    find_known_client_matches,
    should_archive_thread,
)
from workflow import (
    BACKFILL_QUERY,
    DEFAULT_GMAIL_QUERY,
    LIVE_QUERY,
    WORKFLOW_LABELS,
)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class WorkflowQueryTests(unittest.TestCase):
    def test_default_query_excludes_all_labels(self):
        for name in WORKFLOW_LABELS:
            self.assertIn(f'-label:"{name}"', DEFAULT_GMAIL_QUERY)
        self.assertTrue(DEFAULT_GMAIL_QUERY.startswith("in:inbox"))

    def test_live_and_backfill_filters(self):
        self.assertIn("newer_than:2d", LIVE_QUERY)
        self.assertIn("older_than:1d", BACKFILL_QUERY)


class MimeHelperTests(unittest.TestCase):
    def test_has_calendar_part_detects_ics(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/calendar",
                    "filename": "invite.ics",
                    "body": {},
                }
            ],
        }
        self.assertTrue(has_calendar_part(payload))

    def test_has_calendar_part_ignores_plain_text(self):
        payload = {
            "mimeType": "text/plain",
            "filename": "note.txt",
            "body": {},
        }
        self.assertFalse(has_calendar_part(payload))

    def test_decode_body_reads_plain_text(self):
        payload = {
            "mimeType": "text/plain",
            "body": {"data": b64("Hello inbox")},
        }
        self.assertEqual(decode_body(payload), "Hello inbox")

    def test_get_header_is_case_insensitive(self):
        message = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                ]
            }
        }
        self.assertEqual(get_header(message, "subject"), "Hello")


class RoutingTests(unittest.TestCase):
    def test_known_client_match(self):
        clients = [
            {
                "name": "Acme",
                "domains": ["acme.example"],
                "keywords": ["Project Nova"],
            }
        ]
        matches = find_known_client_matches(
            clients,
            "Update",
            "Please review",
            "alice@acme.example",
        )
        self.assertEqual(matches, ["Acme"])

    def test_reply_human_message(self):
        labels = decide_label_names(
            known_client_matches=[],
            relationship="other",
            relationship_confidence=0.80,
            message_type="human_message",
            message_type_confidence=0.90,
            reply_needed=0.80,
            action_required=0.10,
            waiting_on_them=0.10,
        )
        self.assertEqual(labels, ["01 — Reply"])

    def test_uncertain_goes_to_review(self):
        labels = decide_label_names(
            known_client_matches=[],
            relationship="other",
            relationship_confidence=0.20,
            message_type="other",
            message_type_confidence=0.20,
            reply_needed=0.10,
            action_required=0.10,
            waiting_on_them=0.10,
        )
        self.assertEqual(labels, ["98 — Review"])

    def test_confident_empty_goes_to_other(self):
        labels = decide_label_names(
            known_client_matches=[],
            relationship="other",
            relationship_confidence=0.80,
            message_type="other",
            message_type_confidence=0.80,
            reply_needed=0.10,
            action_required=0.10,
            waiting_on_them=0.10,
        )
        self.assertEqual(labels, ["97 — Other"])

    def test_newsletter_archive(self):
        self.assertTrue(
            should_archive_thread(
                message_type="newsletter",
                message_type_confidence=0.80,
                can_archive=0.10,
                reply_needed=0.10,
                action_required=0.10,
            )
        )

    def test_does_not_archive_when_reply_needed(self):
        self.assertFalse(
            should_archive_thread(
                message_type="human_message",
                message_type_confidence=0.90,
                can_archive=0.90,
                reply_needed=0.80,
                action_required=0.10,
            )
        )


if __name__ == "__main__":
    unittest.main()
