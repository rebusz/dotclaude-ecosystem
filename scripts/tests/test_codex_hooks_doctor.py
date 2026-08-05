from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_hooks_doctor as chd  # noqa: E402
import git_hygiene  # noqa: E402


def _encoded_command(target: str) -> str:
    inner = f"& 'C:\\Python314\\python.exe' '{target}'"
    b64 = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    return f"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -EncodedCommand {b64}"


def _adapter_group(matcher: str | None = None) -> dict:
    cmd = _encoded_command("D:\\dotclaude\\dotclaude-ecosystem\\scripts\\codex_session_adapter.py")
    group: dict = {"hooks": [{"type": "command", "command": cmd, "commandWindows": cmd, "timeout": 2}]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _write_codex_hooks(home: Path, hooks: dict) -> None:
    (home / ".codex").mkdir(parents=True, exist_ok=True)
    (home / ".codex" / "hooks.json").write_text(
        json.dumps({"description": "test", "hooks": hooks}), encoding="utf-8")


class DecoderTests(unittest.TestCase):
    def test_encoded_reference_detected(self) -> None:
        cmd = _encoded_command("X:/scripts/codex_session_adapter.py")
        self.assertTrue(chd._references_adapter(cmd))

    def test_plain_reference_detected(self) -> None:
        self.assertTrue(chd._references_adapter('py "X:/scripts/codex_session_adapter.py"'))

    def test_unrelated_command_not_detected(self) -> None:
        self.assertFalse(chd._references_adapter(_encoded_command("X:/other/thing.py")))
        self.assertFalse(chd._references_adapter("py something_else.py"))
        self.assertFalse(chd._references_adapter(None))

    def test_coincidental_substring_not_falsely_recognized(self) -> None:
        # Regression: a foreign command that merely mentions the adapter filename
        # (plain, or encoded as PowerShell -EncodedCommand) must not be treated as
        # an owned handler.
        self.assertFalse(chd._references_adapter(
            'echo "reminder: review codex_session_adapter.py before merging"'))
        mention = _encoded_command("echo see codex_session_adapter.py")  # last quoted token, not a real path
        # _last_quoted_token extracts the final quoted segment; here that segment
        # IS the mention string itself (single-quoted), whose basename is not the
        # adapter filename once treated as a path.
        self.assertFalse(chd._references_adapter(mention))


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_not_deployed_skips(self) -> None:
        v, _ = chd.codex_hooks_status(self.home)
        self.assertEqual(v, "NOT_DEPLOYED")
        self.assertFalse(chd.block_invalidated(v))
        self.assertFalse(chd.deployed(self.home))

    def test_never_installed_when_codex_present_no_hooks(self) -> None:
        (self.home / ".codex").mkdir()
        v, _ = chd.codex_hooks_status(self.home)
        self.assertEqual(v, "NEVER_INSTALLED")
        self.assertTrue(chd.block_invalidated(v))

    def test_ok_when_both_events_reference_adapter(self) -> None:
        _write_codex_hooks(self.home, {
            "SessionStart": [_adapter_group("startup|resume|clear|compact")],
            "SessionEnd": [_adapter_group()],
        })
        v, _ = chd.codex_hooks_status(self.home)
        self.assertEqual(v, "OK")
        self.assertFalse(chd.block_invalidated(v))

    def test_missing_when_one_event_lacks_adapter(self) -> None:
        foreign = {"hooks": [{"type": "command", "command": "py other.py"}]}
        _write_codex_hooks(self.home, {
            "SessionStart": [_adapter_group("startup|resume|clear|compact")],
            "SessionEnd": [foreign],
        })
        v, detail = chd.codex_hooks_status(self.home)
        self.assertEqual(v, "MISSING")
        self.assertIn("SessionEnd", detail)
        self.assertTrue(chd.block_invalidated(v))

    def test_malformed_hooks_json(self) -> None:
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "hooks.json").write_text("{ not json", encoding="utf-8")
        v, _ = chd.codex_hooks_status(self.home)
        self.assertEqual(v, "MALFORMED")
        self.assertTrue(chd.block_invalidated(v))


class JanitorCodexAlarmTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        git_hygiene._managed_hooks_home = self.home

    def tearDown(self) -> None:
        git_hygiene._managed_hooks_home = None
        self._tmp.cleanup()

    def test_alarm_scoped_ascii_on_never_installed(self) -> None:
        (self.home / ".codex").mkdir()
        alarms: list[str] = []
        git_hygiene.check_codex_hooks(alarms)
        self.assertEqual(len(alarms), 1)
        alarms[0].encode("ascii")
        self.assertIn("~/.codex/hooks.json", alarms[0])
        self.assertNotIn("hook absent", alarms[0].lower())

    def test_no_alarm_when_not_deployed(self) -> None:
        alarms: list[str] = []
        git_hygiene.check_codex_hooks(alarms)
        self.assertEqual(alarms, [])

    def test_no_alarm_when_healthy(self) -> None:
        _write_codex_hooks(self.home, {
            "SessionStart": [_adapter_group("startup|resume|clear|compact")],
            "SessionEnd": [_adapter_group()],
        })
        alarms: list[str] = []
        git_hygiene.check_codex_hooks(alarms)
        self.assertEqual(alarms, [])

    def test_alarm_stays_ascii_on_localized_detail(self) -> None:
        # A MALFORMED detail carrying a localized (non-ASCII) OSError strerror must not
        # leak non-ASCII into the alarm (C1). Simulate via a non-ASCII detail.
        orig = chd.codex_hooks_status
        chd.codex_hooks_status = lambda home: ("MALFORMED", "Odmowa dostępu")
        (self.home / ".codex").mkdir()
        alarms: list[str] = []
        try:
            git_hygiene.check_codex_hooks(alarms)
        finally:
            chd.codex_hooks_status = orig
        self.assertEqual(len(alarms), 1)
        alarms[0].encode("ascii")  # must not raise

    def test_check_never_raises(self) -> None:
        orig = chd.codex_hooks_status
        chd.codex_hooks_status = lambda home: (_ for _ in ()).throw(RuntimeError("boom"))
        (self.home / ".codex").mkdir()
        alarms: list[str] = []
        try:
            git_hygiene.check_codex_hooks(alarms)  # must not raise
        finally:
            chd.codex_hooks_status = orig
        self.assertEqual(len(alarms), 1)
        self.assertIn("check failed", alarms[0])


if __name__ == "__main__":
    unittest.main()
