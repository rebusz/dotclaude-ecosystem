#!/usr/bin/env python3
"""Tests for the Codex-to-shared-lifecycle event adapter."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import codex_session_adapter as adapter  # noqa: E402


def _event(
    hook_event_name: str,
    *,
    transcript_path: str | None,
    source: str | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "session_id": "019fa48d-3d90-7eb1-afd3-9fc06757c2c6",
        "transcript_path": transcript_path,
        "cwd": "D:/APPS/ViF",
        "hook_event_name": hook_event_name,
        "model": "gpt-5.6-sol",
    }
    if source is not None:
        event["source"] = source
    if hook_event_name == "SessionEnd":
        event["reason"] = "other"
    return event


class TestCodexSessionAdapter(unittest.TestCase):
    def test_main_treats_non_object_json_as_clean_noop(self):
        for payload in ("[]", "null", '"text"'):
            with self.subTest(payload=payload):
                stdout = io.StringIO()
                with (
                    mock.patch.object(sys, "stdin", io.StringIO(payload)),
                    mock.patch.object(sys, "stdout", stdout),
                ):
                    exit_code = adapter.main()

                self.assertEqual(exit_code, 0)
                self.assertEqual(stdout.getvalue(), "")

    def test_ephemeral_start_is_clean_noop_without_delegation_or_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with (
                mock.patch.object(adapter.session_router, "handle_event") as start,
                mock.patch.object(adapter.session_lifecycle, "handle_event") as end,
            ):
                output = adapter.handle_event(
                    _event(
                        "SessionStart",
                        transcript_path=None,
                        source="startup",
                    ),
                    state_dir=state_dir,
                )

            self.assertEqual(output, {})
            start.assert_not_called()
            end.assert_not_called()
            self.assertFalse((state_dir / "hook_errors.log").exists())

    def test_persisted_start_delegates_exact_event_and_paths(self):
        event = _event(
            "SessionStart",
            transcript_path="C:/Users/test/.codex/sessions/session.jsonl",
            source="startup",
        )
        expected = {
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "registered context",
            }
        }
        shared_output = {
            **expected,
            "hookSpecificOutput": {
                **expected["hookSpecificOutput"],
                "sessionTitle": "shared Claude-only title",
            },
            "sharedOnlyField": "must not reach Codex",
        }
        registry_path = Path("D:/tmp/registry.json")
        state_dir = Path("D:/tmp/state")
        with mock.patch.object(
            adapter.session_router,
            "handle_event",
            return_value=shared_output,
        ) as start:
            output = adapter.handle_event(
                event,
                registry_path=registry_path,
                state_dir=state_dir,
            )

        self.assertEqual(output, expected)
        start.assert_called_once_with(
            event,
            registry_path=registry_path,
            state_dir=state_dir,
            owner_runtime="codex",
        )

    def test_persisted_end_delegates_and_returns_no_stdout_payload(self):
        event = _event(
            "SessionEnd",
            transcript_path="C:/Users/test/.codex/sessions/session.jsonl",
        )
        registry_path = Path("D:/tmp/registry.json")
        state_dir = Path("D:/tmp/state")
        with mock.patch.object(adapter.session_lifecycle, "handle_event") as end:
            output = adapter.handle_event(
                event,
                registry_path=registry_path,
                state_dir=state_dir,
            )

        self.assertEqual(output, {})
        end.assert_called_once_with(
            event,
            registry_path=registry_path,
            state_dir=state_dir,
            owner_runtime="codex",
        )

    def test_null_end_reuses_only_exact_session_binding_transcript(self):
        event = _event("SessionEnd", transcript_path=None)
        state_dir = Path("D:/tmp/state")
        binding = {
            "session_id": event["session_id"],
            "transcript_path": "C:/Users/test/.codex/sessions/bound.jsonl",
        }
        with (
            mock.patch.object(
                adapter,
                "read_session_binding",
                return_value=binding,
            ) as read_binding,
            mock.patch.object(adapter.session_lifecycle, "handle_event") as end,
        ):
            output = adapter.handle_event(event, state_dir=state_dir)

        self.assertEqual(output, {})
        read_binding.assert_called_once_with(
            event["session_id"],
            state_dir=state_dir,
        )
        delegated = dict(event)
        delegated["transcript_path"] = binding["transcript_path"]
        end.assert_called_once_with(
            delegated,
            registry_path=None,
            state_dir=state_dir,
            owner_runtime="codex",
        )
        self.assertIsNone(event["transcript_path"])

    def test_null_end_without_binding_logs_one_bounded_reason_and_noops(self):
        event = _event("SessionEnd", transcript_path=None)
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with (
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=None,
                ),
                mock.patch.object(adapter.session_lifecycle, "handle_event") as end,
            ):
                output = adapter.handle_event(event, state_dir=state_dir)

            self.assertEqual(output, {})
            end.assert_not_called()
            lines = (state_dir / "hook_errors.log").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("CODEX_ADAPTER_END_WITHOUT_BINDING", lines[0])
            self.assertNotIn(str(event["cwd"]), lines[0])

    def test_null_end_with_invalid_session_id_logs_one_adapter_reason(self):
        event = _event("SessionEnd", transcript_path=None)
        event["session_id"] = "../bad"
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            output = adapter.handle_event(event, state_dir=state_dir)

            self.assertEqual(output, {})
            lines = (state_dir / "hook_errors.log").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("CODEX_ADAPTER_INVALID_SESSION_ID ValueError", lines[0])
            self.assertNotIn("../bad", lines[0])

    def test_delegate_exception_fails_open_with_one_adapter_reason(self):
        event = _event(
            "SessionStart",
            transcript_path="C:/Users/test/.codex/sessions/session.jsonl",
            source="startup",
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with mock.patch.object(
                adapter.session_router,
                "handle_event",
                side_effect=RuntimeError("secret transcript text"),
            ):
                output = adapter.handle_event(event, state_dir=state_dir)

            self.assertEqual(output, {})
            line = (state_dir / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("CODEX_ADAPTER_DELEGATE_FAILED RuntimeError", line)
            self.assertNotIn("secret transcript text", line)


if __name__ == "__main__":
    unittest.main()
