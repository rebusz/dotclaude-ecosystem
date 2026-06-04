#!/usr/bin/env python3
"""Tests for terminal_evidence.py."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import terminal_evidence as te


class TestTerminalEvidence(unittest.TestCase):
    def test_success_writes_raw_artifact_and_bounded_summary(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                [sys.executable, "-c", "for i in range(20): print(f'line-{i}')"],
                label="success",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=10,
                max_lines=3,
                max_chars=1000,
            )
            self.assertEqual(code, 0)
            self.assertEqual(summary["exit_code"], 0)
            self.assertEqual(summary["stdout_lines"], 20)
            self.assertEqual(len(summary["tail"]), 3)
            artifact = Path(str(summary["artifact_path"]))
            self.assertTrue(artifact.exists())
            self.assertIn("line-0", artifact.read_text(encoding="utf-8"))
            self.assertTrue(Path(str(summary["summary_path"])).exists())

    def test_failure_exit_code_and_first_failure_are_visible(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                [sys.executable, "-c", "print('AssertionError: bad math'); raise SystemExit(7)"],
                label="failure",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=10,
                max_lines=5,
                max_chars=1000,
            )
            self.assertEqual(code, 7)
            self.assertEqual(summary["exit_code"], 7)
            self.assertTrue(any("AssertionError" in line for line in summary["failures"]))

    def test_stderr_and_repeated_errors_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                [
                    sys.executable,
                    "-c",
                    "import sys\nfor i in range(3): print('ERROR item 123 failed', file=sys.stderr)",
                ],
                label="stderr",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=10,
                max_lines=5,
                max_chars=1000,
            )
            self.assertEqual(code, 0)
            self.assertEqual(summary["stderr_lines"], 3)
            self.assertEqual(summary["repeated_error_groups"][0]["count"], 3)
            artifact_text = Path(str(summary["artifact_path"])).read_text(encoding="utf-8")
            self.assertIn("===== STDERR =====", artifact_text)

    def test_successful_test_names_do_not_create_failure_false_positives(self):
        lines = [
            "test_failure_exit_code_visible (tests.Case.test_failure_exit_code_visible) ... ok",
            "test_stderr_and_repeated_errors_are_preserved (tests.Case.test_stderr_and_repeated_errors_are_preserved) ... ok",
        ]
        failure_rx = re.compile(r"(?i)(failed|failure|error|traceback|assert|exception|timed out)")
        self.assertEqual(te.interesting_lines(lines, failure_rx), [])
        self.assertEqual(te.repeated_groups(lines), [])

    def test_timeout_returns_124_and_keeps_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                [sys.executable, "-c", "import time; print('before'); time.sleep(5)"],
                label="timeout",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=0.2,
                max_lines=5,
                max_chars=1000,
            )
            self.assertEqual(code, te.TIMEOUT_EXIT_CODE)
            self.assertTrue(summary["timed_out"])
            self.assertTrue(any("timed out" in line for line in summary["failures"]))
            self.assertTrue(Path(str(summary["artifact_path"])).exists())

    def test_redacts_summary_but_raw_output_is_full_fidelity(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                [sys.executable, "-c", "print('API_KEY=supersecret')"],
                label="redact",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=10,
                max_lines=5,
                max_chars=1000,
            )
            self.assertEqual(code, 0)
            self.assertIn("API_KEY=[REDACTED]", "\n".join(summary["tail"]))
            artifact_text = Path(str(summary["artifact_path"])).read_text(encoding="utf-8")
            self.assertIn("API_KEY=supersecret", artifact_text)

    def test_refuses_likely_env_dump_without_override(self):
        with tempfile.TemporaryDirectory() as d:
            code, summary = te.run_with_evidence(
                ["env"],
                label="env",
                risk_class="R1",
                cwd=Path(d),
                artifact_dir=Path(d) / "artifacts",
                timeout_s=10,
                max_lines=5,
                max_chars=1000,
            )
            self.assertEqual(code, 2)
            self.assertIsNone(summary["artifact_path"])
            self.assertIn("sensitive command refused", summary["failures"])

    def test_cli_preserves_child_exit_code_and_prints_json(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPTS / "terminal_evidence.py"),
                    "--artifact-dir",
                    str(Path(d) / "artifacts"),
                    "--label",
                    "cli",
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(3)",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 3)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["exit_code"], 3)
            self.assertTrue(Path(summary["artifact_path"]).exists())


if __name__ == "__main__":
    unittest.main()
