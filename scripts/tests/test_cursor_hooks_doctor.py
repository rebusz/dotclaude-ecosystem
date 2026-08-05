from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import cursor_hooks_doctor as chd  # noqa: E402
import git_hygiene  # noqa: E402


def _adapter_handler() -> dict:
    return {"command": 'C:\\Python314\\python.exe "D:/dotclaude/dotclaude-ecosystem/'
                       'scripts/cursor_session_adapter.py"', "timeout": 5}


def _write_cursor_hooks(home: Path, hooks: dict, version: int = 1) -> None:
    (home / ".cursor").mkdir(parents=True, exist_ok=True)
    (home / ".cursor" / "hooks.json").write_text(
        json.dumps({"version": version, "hooks": hooks}), encoding="utf-8")


class ReferenceTests(unittest.TestCase):
    def test_plain_reference_detected(self) -> None:
        self.assertTrue(chd._references_adapter(_adapter_handler()["command"]))

    def test_unrelated_command_not_detected(self) -> None:
        self.assertFalse(chd._references_adapter("py other_script.py"))
        self.assertFalse(chd._references_adapter(None))
        self.assertFalse(chd._references_adapter(123))


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_not_deployed_skips(self) -> None:
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "NOT_DEPLOYED")
        self.assertFalse(chd.block_invalidated(v))
        self.assertFalse(chd.deployed(self.home))

    def test_never_installed_when_cursor_present_no_hooks(self) -> None:
        (self.home / ".cursor").mkdir()
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "NEVER_INSTALLED")
        self.assertTrue(chd.block_invalidated(v))

    def test_ok_when_both_events_reference_adapter(self) -> None:
        _write_cursor_hooks(self.home, {
            "sessionStart": [_adapter_handler()],
            "sessionEnd": [_adapter_handler()],
        })
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "OK")
        self.assertFalse(chd.block_invalidated(v))

    def test_missing_when_one_event_lacks_adapter(self) -> None:
        _write_cursor_hooks(self.home, {
            "sessionStart": [_adapter_handler()],
            "sessionEnd": [{"command": "py other.py"}],
        })
        v, detail = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "MISSING")
        self.assertIn("sessionEnd", detail)
        self.assertTrue(chd.block_invalidated(v))

    def test_missing_when_sessionend_event_absent_entirely(self) -> None:
        _write_cursor_hooks(self.home, {"sessionStart": [_adapter_handler()]})
        v, detail = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "MISSING")
        self.assertIn("sessionEnd", detail)

    def test_malformed_hooks_json(self) -> None:
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor" / "hooks.json").write_text("{ not json", encoding="utf-8")
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "MALFORMED")
        self.assertTrue(chd.block_invalidated(v))

    def test_wrong_version_is_malformed(self) -> None:
        _write_cursor_hooks(self.home, {
            "sessionStart": [_adapter_handler()], "sessionEnd": [_adapter_handler()],
        }, version=2)
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "MALFORMED")

    def test_foreign_handlers_alongside_adapter_still_ok(self) -> None:
        _write_cursor_hooks(self.home, {
            "sessionStart": [{"command": "py foreign.py"}, _adapter_handler()],
            "sessionEnd": [_adapter_handler()],
            "beforeShellExecution": [{"command": "unrelated.sh", "matcher": "curl"}],
        })
        v, _ = chd.cursor_hooks_status(self.home)
        self.assertEqual(v, "OK")


class JanitorCursorAlarmTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        git_hygiene._managed_hooks_home = self.home

    def tearDown(self) -> None:
        git_hygiene._managed_hooks_home = None
        self._tmp.cleanup()

    def test_alarm_scoped_ascii_on_never_installed(self) -> None:
        (self.home / ".cursor").mkdir()
        alarms: list[str] = []
        git_hygiene.check_cursor_hooks(alarms)
        self.assertEqual(len(alarms), 1)
        alarms[0].encode("ascii")
        self.assertIn("~/.cursor/hooks.json", alarms[0])
        self.assertNotIn("hook absent", alarms[0].lower())

    def test_no_alarm_when_not_deployed(self) -> None:
        alarms: list[str] = []
        git_hygiene.check_cursor_hooks(alarms)
        self.assertEqual(alarms, [])

    def test_no_alarm_when_healthy(self) -> None:
        _write_cursor_hooks(self.home, {
            "sessionStart": [_adapter_handler()], "sessionEnd": [_adapter_handler()],
        })
        alarms: list[str] = []
        git_hygiene.check_cursor_hooks(alarms)
        self.assertEqual(alarms, [])

    def test_alarm_stays_ascii_on_localized_detail(self) -> None:
        orig = chd.cursor_hooks_status
        chd.cursor_hooks_status = lambda home: ("MALFORMED", "Odmowa dostępu")
        (self.home / ".cursor").mkdir()
        alarms: list[str] = []
        try:
            git_hygiene.check_cursor_hooks(alarms)
        finally:
            chd.cursor_hooks_status = orig
        self.assertEqual(len(alarms), 1)
        alarms[0].encode("ascii")  # must not raise

    def test_check_never_raises(self) -> None:
        orig = chd.cursor_hooks_status
        chd.cursor_hooks_status = lambda home: (_ for _ in ()).throw(RuntimeError("boom"))
        (self.home / ".cursor").mkdir()
        alarms: list[str] = []
        try:
            git_hygiene.check_cursor_hooks(alarms)  # must not raise
        finally:
            chd.cursor_hooks_status = orig
        self.assertEqual(len(alarms), 1)
        self.assertIn("check failed", alarms[0])


if __name__ == "__main__":
    unittest.main()
