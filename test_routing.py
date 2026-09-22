import base64
import ast
import unittest
from pathlib import Path

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
    WORKER_LOCK_NAME,
    WORKFLOW_LABELS,
)


ROOT = Path(__file__).resolve().parent


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class WorkflowQueryTests(unittest.TestCase):
    def test_default_query_excludes_all_labels(self):
        for name in WORKFLOW_LABELS:
            self.assertIn(f'-label:"{name}"', DEFAULT_GMAIL_QUERY)
        self.assertTrue(DEFAULT_GMAIL_QUERY.startswith("in:inbox"))

    def test_live_and_backfill_do_not_overlap(self):
        self.assertIn("newer_than:1d", LIVE_QUERY)
        self.assertIn("older_than:1d", BACKFILL_QUERY)
        self.assertNotIn("newer_than:2d", LIVE_QUERY)

    def test_workers_share_one_lock_name(self):
        self.assertEqual(WORKER_LOCK_NAME, ".worker.lock")


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

    def test_decode_body_falls_back_to_html(self):
        payload = {
            "mimeType": "text/html",
            "body": {
                "data": b64("<p>Hello <b>HTML</b> only</p>")
            },
        }
        text = decode_body(payload)
        self.assertIn("Hello", text)
        self.assertIn("HTML", text)
        self.assertNotIn("<b>", text)

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
    def test_known_client_domain_matches_headers_only(self):
        clients = [
            {
                "name": "Acme",
                "domains": ["acme.example"],
                "keywords": [],
            }
        ]
        self.assertEqual(
            find_known_client_matches(
                clients,
                "Update",
                "Please review",
                "alice@acme.example",
            ),
            ["Acme"],
        )
        # Body mention alone must not count as a domain match.
        self.assertEqual(
            find_known_client_matches(
                clients,
                "Update",
                "previous project at acme.example was fine",
                "bob@other.example",
            ),
            [],
        )

    def test_known_client_keyword_matches_subject_body(self):
        clients = [
            {
                "name": "Acme",
                "domains": [],
                "keywords": ["Project Nova"],
            }
        ]
        self.assertEqual(
            find_known_client_matches(
                clients,
                "Re: Project Nova kickoff",
                "Looking forward",
                "bob@other.example",
            ),
            ["Acme"],
        )

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


class SafetyInvariantTests(unittest.TestCase):
    def test_dry_run_defaults_to_true_in_main_source(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('env_flag("DRY_RUN", "true")', source)

    def test_live_worker_guards_label_reset_with_dry_run(self):
        source = (ROOT / "live_worker.py").read_text(encoding="utf-8")
        self.assertIn("dry_run=dry_run", source)
        self.assertIn("DRY_RUN: would re-queue", source)
        tree = ast.parse(source)
        fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "remove_old_workflow_labels"
        )
        arg_names = [arg.arg for arg in fn.args.args]
        self.assertIn("dry_run", arg_names)

    def test_migration_runner_requires_apply_opt_in(self):
        source = (ROOT / "migration_runner.py").read_text(encoding="utf-8")
        self.assertIn('env_flag("APPLY_MIGRATION", "false")', source)
        self.assertIn('env["DRY_RUN"] = "false" if apply else "true"', source)

    def test_wrapper_root_is_script_directory(self):
        live = (ROOT / "scripts" / "run_live.sh.example").read_text()
        backfill = (ROOT / "scripts" / "run_backfill.sh.example").read_text()
        self.assertIn('ROOT="$(cd "$(dirname "$0")" && pwd)"', live)
        self.assertIn('ROOT="$(cd "$(dirname "$0")" && pwd)"', backfill)
        self.assertNotIn('/.."', live)
        self.assertNotIn('/.."', backfill)

    def test_env_flag_default_true_without_importing_main(self):
        # Keep this offline: do not import main.py (Google/TypeSafe deps).
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "env_flag"
        )
        self.assertEqual(fn.args.defaults[0].value, "false")
        self.assertIn('env_flag("DRY_RUN", "true")', source)


if __name__ == "__main__":
    unittest.main()
