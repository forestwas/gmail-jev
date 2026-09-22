import base64
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gmail_utils import decode_body, get_header, has_calendar_part
from routing import (
    decide_label_names,
    find_known_client_matches,
    should_archive_thread,
)
from workflow import (
    BACKFILL_QUERY,
    DEFAULT_GMAIL_QUERY,
    HISTORY_RECOVERY_QUERY,
    LIVE_QUERY,
    RECOVERY_PROCESS_QUERY,
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

    def test_history_recovery_query_includes_labeled_mail(self):
        self.assertEqual(HISTORY_RECOVERY_QUERY, "in:inbox newer_than:7d")
        for name in WORKFLOW_LABELS:
            self.assertNotIn(f'-label:"{name}"', HISTORY_RECOVERY_QUERY)

    def test_recovery_process_query_excludes_workflow_labels(self):
        self.assertIn("newer_than:7d", RECOVERY_PROCESS_QUERY)
        for name in WORKFLOW_LABELS:
            self.assertIn(f'-label:"{name}"', RECOVERY_PROCESS_QUERY)

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

    def test_decode_body_skips_filename_text_attachment(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": b64("Visible body")},
                },
                {
                    "mimeType": "text/plain",
                    "filename": "secret-notes.txt",
                    "body": {"data": b64("secret attachment text")},
                },
            ],
        }
        text = decode_body(payload)
        self.assertEqual(text, "Visible body")
        self.assertNotIn("secret", text)

    def test_decode_body_skips_content_disposition_attachment(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": b64("Inline body")},
                },
                {
                    "mimeType": "text/html",
                    "headers": [
                        {
                            "name": "Content-Disposition",
                            "value": 'attachment; filename="page.html"',
                        }
                    ],
                    "body": {"data": b64("<p>Attached HTML secrets</p>")},
                },
            ],
        }
        text = decode_body(payload)
        self.assertEqual(text, "Inline body")
        self.assertNotIn("secrets", text)

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

    def test_newsletter_does_not_archive_when_action_needed(self):
        self.assertFalse(
            should_archive_thread(
                message_type="newsletter",
                message_type_confidence=0.90,
                can_archive=0.05,
                reply_needed=0.10,
                action_required=0.95,
            )
        )

    def test_newsletter_does_not_archive_when_reply_needed(self):
        self.assertFalse(
            should_archive_thread(
                message_type="newsletter",
                message_type_confidence=0.90,
                can_archive=0.05,
                reply_needed=0.95,
                action_required=0.10,
            )
        )

    def test_newsletter_with_high_action_gets_action_label(self):
        labels = decide_label_names(
            known_client_matches=[],
            relationship="other",
            relationship_confidence=0.80,
            message_type="newsletter",
            message_type_confidence=0.90,
            reply_needed=0.10,
            action_required=0.95,
            waiting_on_them=0.10,
        )
        self.assertIn("08 — Read Later", labels)
        self.assertIn("02 — Action Required", labels)

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


class LiveWorkerBehaviorTests(unittest.TestCase):
    def test_process_batches_dry_run_invokes_main_once(self):
        import live_worker

        calls = []
        gmail = MagicMock()

        def fake_run_main(query):
            calls.append(query)
            result = MagicMock()
            result.returncode = 0
            result.stdout = "classified 50 threads"
            return result

        with patch.object(live_worker, "run_main", side_effect=fake_run_main):
            with patch.object(live_worker, "log"):
                ok = live_worker.process_batches(
                    gmail,
                    "in:inbox",
                    label="Live",
                    dry_run=True,
                )

        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)

    def test_process_batches_refuses_success_when_query_never_empties(self):
        import live_worker

        gmail = MagicMock()

        def fake_run_main(query):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "classified some threads"
            return result

        with patch.object(live_worker, "run_main", side_effect=fake_run_main):
            with patch.object(
                live_worker,
                "query_is_empty",
                return_value=False,
            ):
                with patch.object(live_worker, "log"):
                    ok = live_worker.process_batches(
                        gmail,
                        "in:inbox",
                        label="Recovery",
                        dry_run=False,
                        max_batches=3,
                    )

        self.assertFalse(ok)

    def test_process_batches_succeeds_when_main_reports_empty(self):
        import live_worker

        gmail = MagicMock()
        outputs = [
            "classified some",
            "Inbox is empty.",
        ]

        def fake_run_main(query):
            result = MagicMock()
            result.returncode = 0
            result.stdout = outputs.pop(0)
            return result

        with patch.object(live_worker, "run_main", side_effect=fake_run_main):
            with patch.object(live_worker, "log"):
                ok = live_worker.process_batches(
                    gmail,
                    "in:inbox",
                    label="Recovery",
                    dry_run=False,
                    max_batches=5,
                )

        self.assertTrue(ok)
        self.assertEqual(outputs, [])

    def test_process_batches_succeeds_when_final_batch_empties_query(self):
        """Exact-fill regression: last batch processes work but main never
        prints Inbox is empty; post-batch Gmail probe must still succeed."""
        import live_worker

        gmail = MagicMock()
        calls = 0

        def fake_run_main(query):
            nonlocal calls
            calls += 1
            result = MagicMock()
            result.returncode = 0
            result.stdout = f"classified batch {calls}"
            return result

        # After batches 1-4 query still has work; after batch 5 it is empty.
        empty_after = {5}

        def fake_empty(gmail_arg, query):
            return calls in empty_after

        with patch.object(live_worker, "run_main", side_effect=fake_run_main):
            with patch.object(
                live_worker,
                "query_is_empty",
                side_effect=fake_empty,
            ):
                with patch.object(live_worker, "log"):
                    ok = live_worker.process_batches(
                        gmail,
                        "in:inbox",
                        label="Live",
                        dry_run=False,
                        max_batches=5,
                    )

        self.assertTrue(ok)
        self.assertEqual(calls, 5)

    def test_run_recovery_strips_then_uses_shrinking_query(self):
        import live_worker

        gmail = MagicMock()

        with patch.object(
            live_worker,
            "list_thread_ids_for_query",
            return_value=["t1", "t2", "t3"],
        ):
            with patch.dict(os.environ, {"MAX_RESULTS": "100"}):
                with patch.object(
                    live_worker,
                    "remove_old_workflow_labels",
                    return_value=(3, 0),
                ) as strip:
                    with patch.object(
                        live_worker,
                        "process_batches",
                        return_value=True,
                    ) as batches:
                        with patch.object(live_worker, "log"):
                            ok = live_worker.run_recovery(
                                gmail,
                                dry_run=False,
                            )

        self.assertTrue(ok)
        strip.assert_called_once_with(
            gmail,
            ["t1", "t2", "t3"],
            dry_run=False,
        )
        batches.assert_called_once()
        args, kwargs = batches.call_args
        self.assertEqual(args[0], gmail)
        self.assertEqual(args[1], RECOVERY_PROCESS_QUERY)
        self.assertEqual(kwargs.get("label") or args[2], "Recovery")
        self.assertEqual(kwargs.get("max_batches"), 1)

    def test_run_recovery_dry_run_skips_strip_and_loops_once(self):
        import live_worker

        gmail = MagicMock()

        with patch.object(
            live_worker,
            "process_batches",
            return_value=True,
        ) as batches:
            with patch.object(
                live_worker,
                "remove_old_workflow_labels",
            ) as strip:
                with patch.object(live_worker, "log"):
                    ok = live_worker.run_recovery(gmail, dry_run=True)

        self.assertTrue(ok)
        strip.assert_not_called()
        batches.assert_called_once_with(
            gmail,
            HISTORY_RECOVERY_QUERY,
            label="Recovery",
            dry_run=True,
        )

    def test_run_recovery_required_batches_uses_max_results(self):
        import live_worker

        gmail = MagicMock()
        candidates = [f"t{i}" for i in range(250)]

        with patch.object(
            live_worker,
            "list_thread_ids_for_query",
            return_value=candidates,
        ):
            with patch.dict(os.environ, {"MAX_RESULTS": "100"}):
                with patch.object(
                    live_worker,
                    "remove_old_workflow_labels",
                    return_value=(250, 0),
                ):
                    with patch.object(
                        live_worker,
                        "process_batches",
                        return_value=True,
                    ) as batches:
                        with patch.object(live_worker, "log"):
                            live_worker.run_recovery(gmail, dry_run=False)

        self.assertEqual(batches.call_args.kwargs["max_batches"], 3)

    def test_run_recovery_refuses_before_strip_when_over_capacity(self):
        import live_worker

        gmail = MagicMock()
        # 700 candidates / MAX_RESULTS=10 → 70 batches > cap 50
        candidates = [f"t{i}" for i in range(700)]

        with patch.object(
            live_worker,
            "list_thread_ids_for_query",
            return_value=candidates,
        ):
            with patch.dict(os.environ, {"MAX_RESULTS": "10"}):
                with patch.object(
                    live_worker,
                    "remove_old_workflow_labels",
                ) as strip:
                    with patch.object(
                        live_worker,
                        "process_batches",
                    ) as batches:
                        with patch.object(live_worker, "log"):
                            ok = live_worker.run_recovery(
                                gmail,
                                dry_run=False,
                            )

        self.assertFalse(ok)
        strip.assert_not_called()
        batches.assert_not_called()


class EnvFlagTests(unittest.TestCase):
    def test_missing_uses_default(self):
        from env_utils import env_flag

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DRY_RUN", None)
            self.assertTrue(env_flag("DRY_RUN", "true"))
            self.assertFalse(env_flag("APPLY_MIGRATION", "false"))

    def test_accepted_truthy_values(self):
        from env_utils import env_flag

        for value in ("true", "TRUE", "1", "yes", " Yes "):
            with patch.dict(os.environ, {"DRY_RUN": value}):
                self.assertTrue(env_flag("DRY_RUN", "false"), value)

    def test_accepted_falsy_values(self):
        from env_utils import env_flag

        for value in ("false", "FALSE", "0", "no", " No "):
            with patch.dict(os.environ, {"DRY_RUN": value}):
                self.assertFalse(env_flag("DRY_RUN", "true"), value)

    def test_typo_raises_instead_of_opening_writes(self):
        from env_utils import env_flag

        with patch.dict(os.environ, {"DRY_RUN": "tru"}):
            with self.assertRaises(ValueError) as ctx:
                env_flag("DRY_RUN", "true")
        self.assertIn("DRY_RUN", str(ctx.exception))

        with patch.dict(os.environ, {"DRY_RUN": "flase"}):
            with self.assertRaises(ValueError):
                env_flag("DRY_RUN", "true")


class SafetyInvariantTests(unittest.TestCase):
    def test_dry_run_defaults_to_true_in_main_source(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('env_flag("DRY_RUN", "true")', source)
        self.assertIn("from env_utils import env_flag", source)

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
        self.assertIn("Dry-run sample complete", source)
        self.assertIn("if not apply:", source)

    def test_migration_scripts_take_worker_lock(self):
        runner = (ROOT / "migration_runner.py").read_text(encoding="utf-8")
        reset = (ROOT / "migration_reset.py").read_text(encoding="utf-8")
        self.assertIn("exclusive_worker_lock", runner)
        self.assertIn("exclusive_worker_lock", reset)

    def test_live_worker_dry_run_does_not_advance_history(self):
        source = (ROOT / "live_worker.py").read_text(encoding="utf-8")
        self.assertIn(
            'log("DRY_RUN: history checkpoint not advanced.")',
            source,
        )
        self.assertIn("HISTORY_RECOVERY_QUERY", source)
        self.assertIn("RECOVERY_PROCESS_QUERY", source)
        self.assertIn("run_recovery", source)
        self.assertIn("history_expired", source)
        self.assertIn("First live run; running recent inbox recovery", source)
        self.assertIn("max_batches = 1 if dry_run else 5", source)
        self.assertIn("refusing success", source)
        self.assertIn("query_is_empty", source)
        self.assertIn("RECOVERY_MAX_BATCHES", source)
        self.assertIn("refusing before label strip", source)

    def test_wrapper_root_is_script_directory(self):
        live = (ROOT / "scripts" / "run_live.sh.example").read_text()
        backfill = (ROOT / "scripts" / "run_backfill.sh.example").read_text()
        self.assertIn('ROOT="$(cd "$(dirname "$0")" && pwd)"', live)
        self.assertIn('ROOT="$(cd "$(dirname "$0")" && pwd)"', backfill)
        self.assertNotIn('/.."', live)
        self.assertNotIn('/.."', backfill)

    def test_wrappers_do_not_source_dotenv(self):
        live = (ROOT / "scripts" / "run_live.sh.example").read_text()
        backfill = (ROOT / "scripts" / "run_backfill.sh.example").read_text()
        for text in (live, backfill):
            self.assertNotRegex(text, r"(?m)^\s*source\s+\.env\b")
            self.assertNotRegex(text, r"(?m)^\s*\.\s+\.env\b")
        self.assertIn("live_worker.py", live)
        self.assertIn("backfill_worker.py", backfill)

    def test_env_example_quotes_mailbox_owner_name(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn('MAILBOX_OWNER_NAME="the mailbox owner"', text)


if __name__ == "__main__":
    unittest.main()
