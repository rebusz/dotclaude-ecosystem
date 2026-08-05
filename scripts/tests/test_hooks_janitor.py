from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import git_hygiene  # noqa: E402
import hooks_install as hi  # noqa: E402


class JanitorAlarmTests(unittest.TestCase):
    def test_alarm_fires_when_block_missing(self) -> None:
        # A clean fake home -> NEVER_INSTALLED -> block_invalidated -> alarm.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            rep = hi.status(home=home, checkout=ROOT)
            self.assertTrue(hi.block_invalidated(rep))

    def test_alarm_text_is_scoped_and_ascii(self) -> None:
        # C4/Invariant 5: never an unscoped absolute "hook absent" claim; ASCII-safe (C1).
        alarms: list[str] = []
        # monkeypatch status to a MISSING report so the alarm text is exercised
        orig = hi.status

        def fake_status(**kw):
            rep = hi.StatusReport()
            rep.overall = "MISSING"
            return rep
        hi.status = fake_status  # type: ignore[assignment]
        try:
            git_hygiene.check_managed_hooks(alarms)
        finally:
            hi.status = orig  # type: ignore[assignment]
        self.assertEqual(len(alarms), 1)
        text = alarms[0]
        text.encode("ascii")  # raises if any non-ASCII slipped in
        self.assertIn("~/.claude/settings.json", text)
        self.assertIn("checked that file only", text)
        self.assertIn("/hooks", text)
        self.assertNotIn("hook absent", text.lower())  # no unscoped absolute claim

    def test_check_never_crashes_janitor_when_status_raises(self) -> None:
        # C1: a raising hook-status check still lets the janitor complete, surfacing the failure.
        alarms: list[str] = []
        orig = hi.status

        def boom(**kw):
            raise RuntimeError("simulated status failure")
        hi.status = boom  # type: ignore[assignment]
        try:
            git_hygiene.check_managed_hooks(alarms)  # must not raise
        finally:
            hi.status = orig  # type: ignore[assignment]
        self.assertEqual(len(alarms), 1)
        self.assertIn("check failed", alarms[0])
        alarms[0].encode("ascii")

    def test_no_alarm_when_block_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            hi.install(home=home, checkout=ROOT, apply=True)
            alarms: list[str] = []
            orig = hi.status
            hi.status = lambda **kw: orig(home=home, checkout=ROOT)  # type: ignore[assignment]
            try:
                git_hygiene.check_managed_hooks(alarms)
            finally:
                hi.status = orig  # type: ignore[assignment]
            self.assertEqual(alarms, [])

    def test_janitor_liveness_is_not_applicable_on_posix(self) -> None:
        import os
        if os.name != "nt":
            self.assertEqual(hi.janitor_task_status(), "NOT_APPLICABLE")

    # ── Review blocker regression: the deployed janitor runs the flat ~/.claude/scripts
    #    copy, so resolve_checkout(None) (walk-up from __file__) FAILS. The sidecar's
    #    recorded checkout_root must still let the alarm fire. ───────────────────────
    def _simulate_flat_copy(self):
        """Patch resolve_checkout so the __file__ walk-up (explicit=None) fails, exactly
        as it does when git_hygiene runs from ~/.claude/scripts (no .git/templates above)."""
        orig = hi.resolve_checkout

        def patched(explicit):
            if explicit is None:
                raise hi.HookInstallError("simulated flat-copy: no checkout above __file__")
            return orig(explicit)
        return orig, patched

    def test_flat_copy_alarms_via_sidecar_when_block_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            hi.install(home=home, checkout=ROOT, apply=True)      # writes sidecar w/ checkout_root
            (home / ".claude" / "settings.json").unlink()          # block removed after wiring
            orig, patched = self._simulate_flat_copy()
            hi.resolve_checkout = patched
            git_hygiene._managed_hooks_home = home
            alarms: list[str] = []
            try:
                git_hygiene.check_managed_hooks(alarms)
            finally:
                hi.resolve_checkout = orig
                git_hygiene._managed_hooks_home = None
            self.assertEqual(len(alarms), 1, "flat-copy janitor must still alarm via sidecar")
            alarms[0].encode("ascii")
            self.assertIn("~/.claude/settings.json", alarms[0])

    def test_flat_copy_no_alarm_when_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            hi.install(home=home, checkout=ROOT, apply=True)
            orig, patched = self._simulate_flat_copy()
            hi.resolve_checkout = patched
            git_hygiene._managed_hooks_home = home
            alarms: list[str] = []
            try:
                git_hygiene.check_managed_hooks(alarms)
            finally:
                hi.resolve_checkout = orig
                git_hygiene._managed_hooks_home = None
            self.assertEqual(alarms, [], "healthy installed block must not alarm")

    def test_not_deployed_host_skips_silently(self) -> None:
        # No sidecar, resolve_checkout(None) fails, not the installed copy -> skip, no alarm.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            orig, patched = self._simulate_flat_copy()
            hi.resolve_checkout = patched
            git_hygiene._managed_hooks_home = home
            alarms: list[str] = []
            try:
                git_hygiene.check_managed_hooks(alarms)
            finally:
                hi.resolve_checkout = orig
                git_hygiene._managed_hooks_home = None
            self.assertEqual(alarms, [], "non-ecosystem host must not alarm")


if __name__ == "__main__":
    unittest.main()
