#!/usr/bin/env python3
"""Tests for headroom_rtk_benchmark.py helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import headroom_rtk_benchmark as bench  # noqa: E402


class TestHeadroomRtkBenchmark(unittest.TestCase):
    def test_load_b0_source_jsonls_reads_session_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            jsonl = root / "session.jsonl"
            jsonl.write_text("{}", encoding="utf-8")
            session_json = root / "read_heavy_audit.json"
            session_json.write_text(json.dumps({"source_jsonl": str(jsonl)}), encoding="utf-8")
            baseline = root / "baseline.json"
            baseline.write_text(
                json.dumps(
                    {
                        "method": "B0",
                        "mixed_session_baseline": {
                            "sessions": [
                                {
                                    "id": "read_heavy_audit",
                                    "source": str(session_json),
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                bench.load_b0_source_jsonls(baseline, root),
                [{"id": "read_heavy_audit", "jsonl": str(jsonl)}],
            )

    def test_decision_never_defaults_on_from_opportunity_audit_only(self):
        decision = bench.summarize_decision(
            {
                "available": True,
                "metrics": {
                    "read_bytes": 100,
                    "dedup_identical_bytes": 0,
                    "subset_bytes": 0,
                },
            },
            {"available": False},
        )

        self.assertEqual(decision["decision"], "PARK")
        self.assertFalse(decision["default_on"])
        self.assertFalse(decision["ship_gate_pass"])
        self.assertTrue(any("total cost" in reason for reason in decision["reasons"]))


if __name__ == "__main__":
    unittest.main()
