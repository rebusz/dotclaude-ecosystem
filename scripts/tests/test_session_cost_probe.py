#!/usr/bin/env python3
"""Tests for session_cost_probe.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_cost_probe as probe


class TestSessionCostProbe(unittest.TestCase):
    def test_kernel_presence_requires_managed_block_and_needles(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "CLAUDE.md"
            path.write_text(
                "\n".join(
                    [
                        "# Test",
                        probe.BEGIN_MARKER,
                        "Token Budget Protocol",
                        "Risk Classes",
                        "Plan Lifecycle Hooks",
                        probe.END_MARKER,
                    ]
                ),
                encoding="utf-8",
            )
            result = probe.kernel_presence(path)
            self.assertTrue(result["exists"])
            self.assertTrue(result["managed_block"])
            self.assertTrue(result["ok"])

    def test_load_usage_keeps_only_allowlisted_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "usage.json"
            path.write_text(
                json.dumps(
                    {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "prompt_preview": "secret",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                probe.load_usage(path),
                {"input_tokens": 10, "output_tokens": 5},
            )


if __name__ == "__main__":
    unittest.main()
