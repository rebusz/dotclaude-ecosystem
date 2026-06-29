#!/usr/bin/env python3
"""Tests for workflow_os_completion.py."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_cost_probe  # noqa: E402
import workflow_os_completion as completion  # noqa: E402


def _complete_b0(path: Path) -> None:
    sessions = []
    for session_id in session_cost_probe.REQUIRED_B0_SESSION_IDS:
        sessions.append(
            {
                "id": session_id,
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 1,
                    "cache_creation_input_tokens": 0,
                    "cost_usd": 0.01,
                    "startup_context_tokens": 1,
                },
                "quality_baseline": {
                    "summary": "artifact shape preserved",
                    "validation_commands": ["python -m pytest scripts/tests"],
                    "expected_artifacts": ["design/example.md"],
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "method": "B0",
                "mixed_session_baseline": {
                    "sessions": sessions,
                },
            }
        ),
        encoding="utf-8",
    )


class TestWorkflowOSCompletion(unittest.TestCase):
    def test_completion_fails_closed_when_required_artifacts_are_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            triggers = root / "design" / "workflow_os_revisit_triggers.json"
            triggers.parent.mkdir(parents=True)
            triggers.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "manual-gate",
                                "status": "deferred",
                                "trigger_predicate": {
                                    "type": "manual",
                                    "reason": "operator decision",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            status = completion.build_completion_status(
                argparse.Namespace(
                    b0_baseline=root / "missing-b0.json",
                    trigger_file=triggers,
                    section37_decision=root / "missing-section37.json",
                )
            )

            self.assertFalse(status["ready"])
            self.assertFalse(status["b0"]["ready"])
            self.assertFalse(status["section37"]["ready"])
            self.assertFalse(status["triggers"]["ready"])

    def test_completion_accepts_all_ready_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b0 = root / "b0.json"
            _complete_b0(b0)
            section37 = root / "section37.json"
            section37.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "workflow_os_37_operator_decision",
                        "status": "closed_plan_only",
                        "operator_go": True,
                        "evidence": ["operator explicitly closed Section 3.7 as plan-only"],
                    }
                ),
                encoding="utf-8",
            )
            triggers = root / "design" / "workflow_os_revisit_triggers.json"
            triggers.parent.mkdir(parents=True)
            triggers.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "handled-gate",
                                "status": "completed",
                                "completion_note": "handled",
                                "trigger_predicate": {
                                    "type": "manual",
                                    "reason": "operator decision",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            status = completion.build_completion_status(
                argparse.Namespace(
                    b0_baseline=b0,
                    trigger_file=triggers,
                    section37_decision=section37,
                )
            )

            self.assertTrue(status["ready"])
            self.assertTrue(status["b0"]["ready"])
            self.assertTrue(status["section37"]["ready"])
            self.assertTrue(status["triggers"]["ready"])

    def test_triggered_but_unhandled_items_are_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            existing = root / "ready.txt"
            existing.write_text("ready", encoding="utf-8")
            triggers = root / "design" / "workflow_os_revisit_triggers.json"
            triggers.parent.mkdir(parents=True)
            triggers.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "triggered-but-not-handled",
                                "status": "deferred",
                                "trigger_predicate": {
                                    "type": "file_exists",
                                    "path": "ready.txt",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            status = completion.check_triggers(triggers)

            self.assertFalse(status["ready"])
            self.assertEqual(status["pending"][0]["status"], "triggered")


if __name__ == "__main__":
    unittest.main()
