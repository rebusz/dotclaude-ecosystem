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

    def test_b0_status_fails_closed_when_baseline_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            args = type(
                "Args",
                (),
                {
                    "baseline": Path(d) / "missing.json",
                },
            )()

            status = probe.build_b0_status(args)

            self.assertFalse(status["ready"])
            self.assertIn("missing baseline artifact", status["errors"][0])

    def test_b0_status_accepts_complete_mixed_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sessions = []
            for index, session_id in enumerate(probe.REQUIRED_B0_SESSION_IDS, start=1):
                sessions.append(
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
                )
            baseline = root / "workflow_os_b0_mixed_sessions.json"
            baseline.write_text(
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
            args = type(
                "Args",
                (),
                {
                    "baseline": baseline,
                },
            )()

            status = probe.build_b0_status(args)

            self.assertTrue(status["ready"])
            self.assertEqual(status["errors"], [])
            self.assertEqual(status["session_ids"], sorted(probe.REQUIRED_B0_SESSION_IDS))

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

    def test_parse_claude_jsonl_usage_aggregates_usage_without_prompt_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session.jsonl"
            rows = [
                {
                    "timestamp": "2026-06-29T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-test",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cache_creation_input_tokens": 3,
                            "cache_read_input_tokens": 7,
                        },
                    },
                },
                {
                    "timestamp": "2026-06-29T00:01:00Z",
                    "message": {
                        "role": "assistant",
                        "model": "claude-test",
                        "usage": {
                            "input_tokens": 2,
                            "output_tokens": 4,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 1,
                        },
                    },
                },
                {"message": {"role": "user", "content": "do not include me"}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            summary = probe.parse_claude_jsonl_usage(path)
            self.assertEqual(summary["usage_messages"], 2)
            self.assertEqual(summary["usage"]["input_tokens"], 12)
            self.assertEqual(summary["usage"]["output_tokens"], 9)
            self.assertEqual(summary["usage"]["cache_creation_input_tokens"], 3)
            self.assertEqual(summary["usage"]["cache_read_input_tokens"], 8)
            self.assertEqual(summary["usage"]["total_tokens"], 32)
            self.assertEqual(summary["models"], ["claude-test"])
            self.assertEqual(summary["first_timestamp"], "2026-06-29T00:00:00Z")
            self.assertEqual(summary["last_timestamp"], "2026-06-29T00:01:00Z")

    def test_build_b0_session_from_jsonl_requires_explicit_cost(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "message": {
                            "role": "assistant",
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 7,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "jsonl": path,
                    "session_id": "read_heavy_audit",
                    "label": "",
                    "cost_usd": 0.12,
                    "startup_context_tokens": 1000,
                    "quality_summary": "baseline artifact shape held",
                    "validation_command": ["python -m pytest scripts/tests"],
                    "expected_artifact": [],
                },
            )()

            session = probe.build_b0_session_from_jsonl(args)
            self.assertEqual(session["usage_source"], "claude-jsonl-plus-explicit-cost")
            self.assertEqual(session["usage"]["cost_usd"], 0.12)
            self.assertEqual(session["usage"]["cache_read_input_tokens"], 7)

    def test_build_jsonl_inventory_sorts_candidates_without_prompt_text(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            small = directory / "small.jsonl"
            large = directory / "large.jsonl"
            small.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-29T00:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "do not leak small"}],
                            "usage": {
                                "input_tokens": 1,
                                "output_tokens": 1,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            large.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-29T00:01:00Z",
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "do not leak large"}],
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 100,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            inventory = probe.build_jsonl_inventory(directory, limit=10, min_usage_messages=1)
            self.assertEqual(inventory["redaction"], "prompt_content_omitted")
            self.assertEqual(inventory["session_count"], 2)
            self.assertEqual(inventory["sessions"][0]["filename"], "large.jsonl")
            self.assertEqual(inventory["sessions"][0]["usage"]["total_tokens"], 115)
            inventory_text = json.dumps(inventory)
            self.assertNotIn("do not leak small", inventory_text)
            self.assertNotIn("do not leak large", inventory_text)


if __name__ == "__main__":
    unittest.main()
