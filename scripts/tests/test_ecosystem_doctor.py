#!/usr/bin/env python3
"""Tests for the delivery seam (audit 2026-09-09, Slice B).

The whole point of this module is that a detector's verdict reaches somewhere a
person will look. So the properties worth pinning are not "does it detect" — the
underlying detectors already did, correctly, for weeks — but:

  * a dirty state produces a non-zero exit AND a line naming what is wrong;
  * a check that could not run is never counted as a pass;
  * the line stays inside its budget however many things are broken;
  * nothing it does can break the SessionStart hook that consumes it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import ecosystem_doctor as doc  # noqa: E402  (sys.path must be set first)
import session_router  # noqa: E402

_HOUR = 3600.0


def _home(tmp: Path) -> Path:
    (tmp / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    return tmp


def _state(tmp: Path) -> Path:
    return tmp / ".claude" / "state"


class ReportVerdictTests(unittest.TestCase):
    """exit_code() and line() are the contract every consumer reads."""

    def test_nothing_checked_is_not_reported_as_clean(self) -> None:
        report = doc.Report([doc.Check("a", True, "skipped", checked=False)])
        self.assertEqual(report.exit_code(), 2)
        self.assertNotIn("clean", report.line())

    def test_a_dirty_check_exits_three_and_is_named(self) -> None:
        report = doc.Report(
            [doc.Check("hooks", True, "OK"), doc.Check("verdicts", False, "1601 unreaped")]
        )
        self.assertEqual(report.exit_code(), 3)
        line = report.line()
        self.assertIn("verdicts=1601 unreaped", line)
        self.assertNotIn("hooks", line, "the line names what is wrong, not what is right")

    def test_all_clean_exits_zero(self) -> None:
        report = doc.Report([doc.Check("hooks", True, "OK"), doc.Check("temp", True, "0")])
        self.assertEqual(report.exit_code(), 0)
        self.assertIn("clean", report.line())

    def test_line_stays_within_budget_however_much_is_broken(self) -> None:
        report = doc.Report(
            [doc.Check(f"check{i}", False, "x" * 60) for i in range(12)]
        )
        line = report.line()
        self.assertLessEqual(len(line), doc.LINE_BUDGET)
        self.assertIn("more", line, "the overflow must be counted, not dropped silently")

    def test_json_shape_carries_the_exit_code(self) -> None:
        payload = doc.Report([doc.Check("x", False, "bad")]).to_dict()
        self.assertEqual(payload["exit_code"], 3)
        self.assertEqual(payload["checks"][0]["ok"], False)
        json.dumps(payload)  # must stay serialisable


class VerdictBacklogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))

    def test_a_normal_backlog_passes(self) -> None:
        for i in range(5):
            (_state(self.home) / f"session_verdict_{i}.json").write_text("{}", encoding="utf-8")
        check = doc._check_verdict_backlog(_state(self.home))
        self.assertTrue(check.ok)

    def test_an_unbounded_backlog_fails(self) -> None:
        for i in range(doc.VERDICT_BACKLOG_CEILING + 2):
            (_state(self.home) / f"session_verdict_{i}.json").write_text("{}", encoding="utf-8")
        check = doc._check_verdict_backlog(_state(self.home))
        self.assertFalse(check.ok)
        self.assertIn("unreaped", check.detail)

    def test_the_backlog_check_never_opens_a_verdict(self) -> None:
        """Reading each JSON is exactly what makes the reaper's own scan O(N);
        this runs on every SessionStart and must not repeat that."""
        for i in range(50):
            (_state(self.home) / f"session_verdict_{i}.json").write_text("{}", encoding="utf-8")
        real_open = Path.read_text
        with mock.patch.object(Path, "read_text", autospec=True) as opened:
            opened.side_effect = real_open
            doc._check_verdict_backlog(_state(self.home))
        opened.assert_not_called()


class LeakedTempTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))
        self.now = time.time()

    def _leak(self, name: str, age_hours: float) -> None:
        path = _state(self.home) / name
        path.write_text("x", encoding="utf-8")
        stamp = self.now - age_hours * _HOUR
        import os

        os.utime(path, (stamp, stamp))

    def test_fresh_temp_files_are_ignored(self) -> None:
        for i in range(10):
            self._leak(f".thing{i}.json.abc.tmp", age_hours=1)
        self.assertTrue(doc._check_leaked_temp(self.home, _state(self.home), self.now).ok)

    def test_a_pile_of_old_temp_files_fails(self) -> None:
        for i in range(doc.LEAKED_TMP_CEILING + 2):
            self._leak(f".thing{i}.json.abc.tmp", age_hours=48)
        check = doc._check_leaked_temp(self.home, _state(self.home), self.now)
        self.assertFalse(check.ok)
        self.assertIn("orphaned", check.detail)


class JanitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))
        self.dir = _state(self.home) / "git_hygiene"
        self.dir.mkdir(parents=True)
        self.now = time.time()

    def _report(self, name: str, body: str, age_hours: float = 1.0) -> None:
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        stamp = self.now - age_hours * _HOUR
        import os

        os.utime(path, (stamp, stamp))

    def test_alarms_in_the_cached_report_are_counted(self) -> None:
        self._report(
            "report-latest_repo.txt",
            "=== git_hygiene [DRY-RUN] ===\n\nALARMS:\n  ! PRIMARY off main\n  ! MANAGED HOOKS: COLLISION\n",
        )
        check = doc._check_janitor(_state(self.home), self.now)
        self.assertFalse(check.ok)
        self.assertIn("2 alarms", check.detail)

    def test_a_quiet_report_passes(self) -> None:
        self._report("report-latest_repo.txt", "=== git_hygiene ===\nno alarms\n")
        self.assertTrue(doc._check_janitor(_state(self.home), self.now).ok)

    def test_a_stale_report_means_the_scheduler_stopped(self) -> None:
        self._report("report-latest_repo.txt", "clean\n", age_hours=doc.JANITOR_STALE_HOURS + 5)
        check = doc._check_janitor(_state(self.home), self.now)
        self.assertFalse(check.ok)
        self.assertIn("old", check.detail)

    def test_no_janitor_deployed_is_unchecked_not_clean(self) -> None:
        check = doc._check_janitor(Path(self._tmp.name) / "nowhere", self.now)
        self.assertFalse(check.checked)


class BuildReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))

    def test_an_exhausted_budget_marks_checks_skipped_not_passed(self) -> None:
        report = doc.build_report(home=self.home, state_dir=_state(self.home), budget_s=0.0)
        skipped = [c for c in report.checks if not c.checked]
        self.assertTrue(skipped, "a spent budget must be visible")
        self.assertTrue(all("budget" in c.detail for c in skipped if c.detail.startswith("skipped")))

    def test_a_raising_check_is_unchecked_not_a_silent_pass(self) -> None:
        with mock.patch.object(doc, "_check_verdict_backlog", side_effect=RuntimeError("boom")):
            report = doc.build_report(home=self.home, state_dir=_state(self.home))
        verdicts = next(c for c in report.checks if c.name == "verdicts")
        self.assertFalse(verdicts.checked)
        self.assertFalse(verdicts.ok)
        self.assertIn("RuntimeError", verdicts.detail)

    def test_the_cli_exit_code_matches_the_report(self) -> None:
        for i in range(doc.VERDICT_BACKLOG_CEILING + 2):
            (_state(self.home) / f"session_verdict_{i}.json").write_text("{}", encoding="utf-8")
        code = doc.main(["--home", str(self.home), "--state-dir", str(_state(self.home))])
        self.assertEqual(code, 3)

    def test_the_module_runs_as_a_script(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / "ecosystem_doctor.py"),
             "--home", str(self.home), "--state-dir", str(_state(self.home)), "--json"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["exit_code"], result.returncode)


class SessionRouterWiringTests(unittest.TestCase):
    """The seam only counts if the hook actually carries it."""

    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = _home(Path(self._tmp.name))

    def test_a_dirty_ecosystem_produces_a_context_line(self) -> None:
        for i in range(doc.VERDICT_BACKLOG_CEILING + 2):
            (_state(self.home) / f"session_verdict_{i}.json").write_text("{}", encoding="utf-8")
        line = session_router._ecosystem_health_line(_state(self.home), home=self.home)
        self.assertIn("NEEDS ATTENTION", line)
        self.assertLessEqual(len(line), doc.LINE_BUDGET)

    def test_a_clean_ecosystem_says_nothing(self) -> None:
        line = session_router._ecosystem_health_line(_state(self.home), home=self.home)
        self.assertEqual(line, "", "a healthy box must cost no context")

    def test_an_installed_home_missing_the_block_still_fails(self) -> None:
        """The distinction must not become a way to hide the real failure: a
        home that HAS a settings.json and no managed block is exactly the
        IDEA_BOX death this seam exists to surface."""
        (self.home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        check = doc._check_hook_block(self.home, None)
        self.assertTrue(check.checked, "an installed home must be judged, not skipped")
        self.assertFalse(check.ok)

    def test_a_broken_doctor_never_breaks_session_start(self) -> None:
        with mock.patch.object(doc, "build_report", side_effect=RuntimeError("boom")):
            line = session_router._ecosystem_health_line(_state(self.home), home=self.home)
        self.assertEqual(line, "")


if __name__ == "__main__":
    unittest.main()
