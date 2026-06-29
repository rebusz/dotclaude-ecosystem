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

import session_cost_probe as probe  # noqa: E402


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

    def test_build_b0_baseline_requires_three_measured_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            session_paths = []
            for index, session_id in enumerate(probe.REQUIRED_B0_SESSION_IDS, start=1):
                path = root / f"{session_id}.json"
                path.write_text(
                    json.dumps(
                        {
                            "id": session_id,
                            "usage": {
                                "input_tokens": 100 * index,
                                "output_tokens": 10 * index,
                                "cache_read_input_tokens": 20 * index,
                                "cache_creation_input_tokens": 5 * index,
                                "cost_usd": 0.01 * index,
                                "startup_context_tokens": 1000,
                            },
                            "quality_baseline": {
                                "summary": "produced the expected artifact shape",
                                "validation_commands": ["python -m pytest scripts/tests"],
                                "expected_artifacts": ["design/example.md"],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                session_paths.append(path)

            sessions = [probe.load_b0_session(path) for path in session_paths]
            summary = probe.summarize_b0_sessions(sessions)

            self.assertEqual(summary["session_count"], 3)
            self.assertEqual(summary["totals"]["input_tokens"], 600)
            self.assertEqual(summary["totals"]["output_tokens"], 60)
            self.assertEqual(summary["totals"]["cache_read_input_tokens"], 120)
            self.assertEqual(summary["totals"]["cache_creation_input_tokens"], 30)
            self.assertEqual(summary["totals"]["startup_context_tokens"], 3000)

    def test_b0_session_rejects_missing_required_usage(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "read_heavy_audit.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "read_heavy_audit",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cache_read_input_tokens": 20,
                            "cost_usd": 0.01,
                        },
                        "quality_baseline": {
                            "summary": "produced the expected artifact shape",
                            "validation_commands": ["python -m pytest scripts/tests"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "startup_context_tokens"):
                probe.load_b0_session(path)

    def test_probe_records_extra_kernel_presence_targets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("CLAUDE.md", "AGENTS.md", "cline.md", "GEMINI.md"):
                (root / name).write_text(
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

            args = type(
                "Args",
                (),
                {
                    "repo_root": root,
                    "claude_file": root / "CLAUDE.md",
                    "codex_file": root / "AGENTS.md",
                    "cline_file": root / "cline.md",
                    "antigravity_file": root / "GEMINI.md",
                    "method": "A1",
                    "note": "",
                    "usage_json": None,
                    "skip_sync_check": True,
                },
            )()

            data = probe.build_probe(args)
            self.assertTrue(data["files"]["cline_global"]["ok"])
            self.assertTrue(data["files"]["antigravity_global"]["ok"])

    def test_compare_metric_reports_new_global_file_missing_from_old_baseline(self):
        baseline = {"files": {}}
        current = {
            "files": {
                "antigravity_global": {
                    "exists": True,
                    "ok": True,
                    "bytes": 10,
                    "lines": 2,
                    "sha256": "new",
                }
            }
        }

        metric = probe._compare_metric("antigravity_global", baseline, current)
        self.assertTrue(metric["exists"])
        self.assertTrue(metric["kernel_ok"])
        self.assertEqual(metric["bytes_delta"], 10)
        self.assertTrue(metric["sha_changed"])


if __name__ == "__main__":
    unittest.main()
