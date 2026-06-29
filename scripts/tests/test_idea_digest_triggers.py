#!/usr/bin/env python3
"""Tests for Workflow OS revisit trigger evaluation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import idea_digest


class TestWorkflowTriggers(unittest.TestCase):
    def test_file_contains_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "handoff.md").write_text("Slice 0 (kernel-slim) SHIPPED", encoding="utf-8")
            status, reason = idea_digest.evaluate_trigger(
                {"type": "file_contains", "path": "handoff.md", "needle": "SHIPPED"},
                base,
            )
            self.assertEqual(status, "triggered")
            self.assertIn("found needle", reason)

    def test_manual_trigger_is_not_auto_triggered(self):
        status, reason = idea_digest.evaluate_trigger(
            {"type": "manual", "reason": "operator decision"},
            Path.cwd(),
        )
        self.assertEqual(status, "manual")
        self.assertEqual(reason, "operator decision")

    def test_file_exists_trigger_defers_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            status, reason = idea_digest.evaluate_trigger(
                {"type": "file_exists", "path": "missing.json"},
                Path(d),
            )
            self.assertEqual(status, "deferred")
            self.assertIn("missing file", reason)

    def test_command_exit_zero_trigger_defers_on_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            status, reason = idea_digest.evaluate_trigger(
                {
                    "type": "command_exit_zero",
                    "command": [sys.executable, "-c", "raise SystemExit(1)"],
                },
                Path(d),
            )
            self.assertEqual(status, "deferred")
            self.assertIn("exit 1", reason)


if __name__ == "__main__":
    unittest.main()
