#!/usr/bin/env python3
"""Tests for Workflow OS revisit trigger evaluation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


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
        # This used `[sys.executable, "-c", "raise SystemExit(1)"]` -- inline
        # code from the trigger file, the exact capability that made the file an
        # unattended code-execution vector (audit security F1). Same intent,
        # through the one form still allowed: a script inside scripts/.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "scripts").mkdir()
            (base / "scripts" / "session_cost_probe.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            status, reason = idea_digest.evaluate_trigger(
                {
                    "type": "command_exit_zero",
                    "command": ["python", "scripts/session_cost_probe.py", "b0-status"],
                },
                base,
            )
            self.assertEqual(status, "deferred")
            self.assertIn("exit 1", reason)



class TestTriggerContainment(unittest.TestCase):
    """The trigger file is repository content evaluated daily, unattended, on
    the trading workstation. Every predicate must stay inside its repository
    (audit security F1)."""

    def _repo(self, d: str) -> Path:
        base = Path(d)
        (base / "scripts").mkdir()
        (base / "scripts" / "session_cost_probe.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        (base / "scripts" / "git_hygiene.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        return base

    def test_an_arbitrary_argv_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._repo(d)
            for argv in (["powershell", "-c", "whoami"], ["cmd", "/c", "echo", "x"],
                         ["git", "status"], ["python", "-c", "print(1)"]):
                with self.subTest(argv=argv):
                    status, reason = idea_digest.evaluate_trigger(
                        {"type": "command_exit_zero", "command": argv}, base)
                    self.assertEqual(status, "blocked")
                    self.assertIn("allowlisted probe", reason)

    def test_a_mutating_repo_script_or_other_subcommand_is_refused(self):
        """Containment to scripts/ was not least privilege: the mutating tools
        live there too."""
        with tempfile.TemporaryDirectory() as d:
            base = self._repo(d)
            for argv in (["python", "scripts/git_hygiene.py", "--apply", "--deploy"],
                         ["python", "scripts/session_cost_probe.py", "record"],
                         ["python", "scripts/session_cost_probe.py"]):
                with self.subTest(argv=argv):
                    status, _ = idea_digest.evaluate_trigger(
                        {"type": "command_exit_zero", "command": argv}, base)
                    self.assertEqual(status, "blocked")

    def test_a_script_outside_scripts_or_outside_the_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._repo(d)
            (base / "evil.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            for script in ("evil.py", "scripts/../evil.py", "../../outside.py",
                           str(Path(d).parent / "outside.py")):
                with self.subTest(script=script):
                    status, _ = idea_digest.evaluate_trigger(
                        {"type": "command_exit_zero", "command": ["python", script, "b0-status"]}, base)
                    self.assertEqual(status, "blocked")

    def test_the_legitimate_form_still_runs_with_this_interpreter(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._repo(d)
            status, reason = idea_digest.evaluate_trigger(
                {"type": "command_exit_zero",
                 "command": ["python", "scripts/session_cost_probe.py", "b0-status", "--baseline", "x.json"]},
                base)
            self.assertEqual(status, "triggered", reason)

    def test_paths_cannot_probe_outside_the_repository(self):
        """Absolute paths used to be returned unchanged: a file-existence and
        needle oracle over the whole disk."""
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            secret = Path(other) / "somewhere.txt"
            secret.write_text("needle", encoding="utf-8")
            for predicate in ({"type": "file_exists", "path": str(secret)},
                              {"type": "file_contains", "path": str(secret), "needle": "needle"},
                              {"type": "file_exists", "path": "../" + secret.name}):
                with self.subTest(predicate=predicate["type"]):
                    status, _ = idea_digest.evaluate_trigger(predicate, Path(d))
                    self.assertEqual(status, "blocked")

    def test_a_pr_value_cannot_become_a_gh_flag(self):
        with tempfile.TemporaryDirectory() as d:
            status, _ = idea_digest.evaluate_trigger(
                {"type": "github_pr_state", "repo": d, "pr": "--repo=other/x", "state": "MERGED"},
                Path(d))
            self.assertEqual(status, "blocked")


if __name__ == "__main__":
    unittest.main()
