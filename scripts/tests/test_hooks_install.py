from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import hooks_install as hi  # noqa: E402


def _settings(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _write_settings(home: Path, value) -> None:
    p = _settings(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        p.write_text(json.dumps(value, indent=2), encoding="utf-8")
    else:
        p.write_text(value, encoding="utf-8")


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── dry-run purity ────────────────────────────────────────────────
    def test_dry_run_writes_nothing(self) -> None:
        res = hi.install(home=self.home, checkout=ROOT, apply=False)
        self.assertEqual(res["mode"], "dry-run")
        self.assertFalse(res["wrote_backup"])
        self.assertFalse(_settings(self.home).exists())
        self.assertIsNone(hi.read_sidecar(self.home))
        self.assertFalse((self.home / ".claude" / "backups").exists())
        self.assertEqual(len(res["changes"]["added"]), 10)

    # ── apply creates block + sidecar ─────────────────────────────────
    def test_apply_creates_block_and_sidecar(self) -> None:
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        # 10 managed handlers across 5 events
        total = sum(len(g["hooks"]) for groups in settings["hooks"].values() for g in groups)
        self.assertEqual(total, 10)
        sidecar = hi.read_sidecar(self.home)
        self.assertEqual(sidecar["state"], "installed")
        self.assertEqual(len(sidecar["entries"]), 10)
        rep = hi.status(home=self.home, checkout=ROOT)
        self.assertEqual(rep.overall, "OK")

    # ── idempotent reinstall, no double-fire ──────────────────────────
    def test_reinstall_is_byte_stable_and_no_double_fire(self) -> None:
        hi.install(home=self.home, checkout=ROOT, apply=True)
        first = _settings(self.home).read_bytes()
        res2 = hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertEqual(res2["mode"], "applied-noop")
        self.assertFalse(res2["wrote_backup"])
        self.assertEqual(_settings(self.home).read_bytes(), first)
        settings = json.loads(first)
        total = sum(len(g["hooks"]) for groups in settings["hooks"].values() for g in groups)
        self.assertEqual(total, 10)  # not 20

    # ── audit P1-1: a SECOND checkout must reconcile, not duplicate ───
    def _fake_checkout(self, name: str) -> Path:
        """A directory that satisfies resolve_checkout + _validated_context."""
        root = Path(self._tmp.name) / name
        (root / "templates").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        (root / "templates" / "hooks.manifest.json").write_bytes(
            (ROOT / "templates" / "hooks.manifest.json").read_bytes()
        )
        for entry in hi.load_manifest(ROOT):
            (root / "scripts" / entry.script).write_text("# stub", encoding="utf-8")
        return root

    def _handler_count(self) -> int:
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        return sum(len(g["hooks"]) for groups in settings["hooks"].values() for g in groups)

    def _commands(self) -> list[str]:
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        return [h["command"] for groups in settings["hooks"].values()
                for g in groups for h in g["hooks"]]

    def test_install_from_a_second_checkout_reconciles_instead_of_duplicating(self) -> None:
        """The live box reached 20 handlers exactly this way: the previous
        checkout's handlers were classified `collision`, kept in place, and the
        new canonical group was appended on top of them."""
        hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertEqual(self._handler_count(), 10)

        second = self._fake_checkout("checkout-b")
        hi.install(home=self.home, checkout=second, apply=True)

        self.assertEqual(self._handler_count(), 10, "second checkout must not double the block")
        resolved = second.resolve(strict=False).as_posix()
        self.assertTrue(all(resolved in c for c in self._commands()))
        self.assertIn(hi._canonical_root(str(ROOT)), hi.read_sidecar(self.home)["previous_roots"])
        self.assertEqual(hi.status(home=self.home, checkout=second).overall, "OK")

    def test_third_checkout_reconciles_using_the_recorded_root_history(self) -> None:
        second = self._fake_checkout("checkout-b")
        third = self._fake_checkout("checkout-c")
        hi.install(home=self.home, checkout=ROOT, apply=True)
        hi.install(home=self.home, checkout=second, apply=True)
        hi.install(home=self.home, checkout=third, apply=True)

        self.assertEqual(self._handler_count(), 10)
        self.assertEqual(sorted(hi.read_sidecar(self.home)["previous_roots"]),
                         sorted([hi._canonical_root(str(ROOT)), hi._canonical_root(str(second))]))

    def test_a_short_path_spelling_resolves_to_the_same_root(self) -> None:
        """CI caught this: the GitHub runner's TEMP is an 8.3 short path
        (C:/Users/RUNNER~1/...) while the sidecar records the resolved form, so
        a plain string comparison failed to recognise our own handlers — the
        exact duplication this ownership record exists to prevent."""
        if sys.platform != "win32":
            self.skipTest("8.3 short names are a Windows filesystem feature")
        long_form = Path("C:/Program Files")
        if not long_form.is_dir():
            self.skipTest("no directory with a known 8.3 alias on this host")
        self.assertEqual(hi._canonical_root("C:/PROGRA~1"), hi._canonical_root(str(long_form)))

    def test_a_recorded_root_that_no_longer_exists_is_not_claimed(self) -> None:
        """Ownership expires with the checkout. Once the directory is gone the
        path can be reused by something unrelated, and claiming a handler under
        it would delete a hook we never wrote."""
        second = self._fake_checkout("checkout-b")
        hi.install(home=self.home, checkout=second, apply=True)
        hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertIn(hi._canonical_root(str(second)), hi.read_sidecar(self.home)["previous_roots"])

        shutil.rmtree(second)
        ownership = hi.sidecar_ownership(self.home)

        self.assertNotIn(hi._canonical_root(str(second)), ownership.roots)
        self.assertIn(hi._canonical_root(str(ROOT)), ownership.roots)

    def test_unrecorded_root_stays_a_collision_until_reconcile(self) -> None:
        """Ownership is proof, not a guess: a managed basename under a root we
        never recorded is surfaced, never silently deleted."""
        interp = hi.resolve_interpreter()
        stranger = f'{interp} "D:/somewhere/else/scripts/session_router.py"'
        _write_settings(self.home, {"hooks": {"SessionStart": [
            {"matcher": "startup|resume|clear|compact",
             "hooks": [{"type": "command", "command": stranger}]}]}})

        res = hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertEqual(len(res["collisions"]), 1)
        self.assertEqual(self._handler_count(), 11, "the stranger is kept, not deleted")
        self.assertIn(stranger, self._commands())

        res2 = hi.install(home=self.home, checkout=ROOT, apply=True, reconcile=True)
        self.assertEqual(res2["collisions"], [])
        self.assertEqual(self._handler_count(), 10)
        self.assertNotIn(stranger, self._commands())

    def test_reconcile_never_touches_a_foreign_basename(self) -> None:
        interp = hi.resolve_interpreter()
        foreign = f'{interp} "D:/somewhere/else/scripts/not_ours.py"'
        _write_settings(self.home, {"hooks": {"SessionStart": [
            {"matcher": "startup|resume|clear|compact",
             "hooks": [{"type": "command", "command": foreign}]}]}})

        hi.install(home=self.home, checkout=ROOT, apply=True, reconcile=True)

        self.assertIn(foreign, self._commands())
        self.assertEqual(self._handler_count(), 11)

    def test_cli_install_exits_3_while_a_collision_remains(self) -> None:
        interp = hi.resolve_interpreter()
        stranger = f'{interp} "D:/somewhere/else/scripts/session_router.py"'
        _write_settings(self.home, {"hooks": {"SessionStart": [
            {"matcher": "startup|resume|clear|compact",
             "hooks": [{"type": "command", "command": stranger}]}]}})

        dirty = hi.main(["install", "--apply", "--home", str(self.home), "--checkout", str(ROOT)])
        self.assertEqual(dirty, 3, "a dirty block must not report success")

        clean = hi.main(["install", "--apply", "--reconcile",
                         "--home", str(self.home), "--checkout", str(ROOT)])
        self.assertEqual(clean, 0)

    # ── Matrix B1: foreign handler in a shared group survives ─────────
    def test_foreign_handler_in_shared_group_preserved(self) -> None:
        interp = hi.resolve_interpreter()
        managed_cmd = hi.render_command(interp, ROOT, "autocommit_design_docs.py")
        foreign_cmd = f'{interp} "{(self.home / ".claude" / "scripts" / "my_custom_hook.py").as_posix()}"'
        _write_settings(self.home, {"hooks": {"PostToolUse": [
            {"matcher": "Write", "hooks": [
                {"type": "command", "command": managed_cmd},
                {"type": "command", "command": foreign_cmd},
            ]},
        ]}})
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        all_cmds = [h["command"] for g in settings["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertIn(foreign_cmd, all_cmds)          # foreign survived in place
        # autocommit is canonical on both Write and Edit (2), never 3 (seeded copy removed)
        self.assertEqual(all_cmds.count(managed_cmd), 2)

    # ── double-fire prevention: hand-wired home-path entry is migrated ─
    def test_handwired_home_path_entry_migrated_not_duplicated(self) -> None:
        # legacy hand-wired form pointing at ~/.claude/scripts (allowlisted legacy root)
        legacy = f'py "{(self.home / ".claude" / "scripts" / "plan_keyword_detector.py").as_posix()}"'
        _write_settings(self.home, {"hooks": {"UserPromptSubmit": [
            {"matcher": "*", "hooks": [{"type": "command", "command": legacy}]},
        ]}})
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        cmds = [h["command"] for g in settings["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertEqual(len(cmds), 1)                # migrated, not duplicated
        self.assertNotIn(legacy, cmds)               # rewritten to canonical checkout path
        self.assertIn("scripts/plan_keyword_detector.py", cmds[0])

    # ── malformed settings fail closed, no write ──────────────────────
    def test_malformed_settings_fail_closed(self) -> None:
        _write_settings(self.home, "{ this is not json ")
        original = _settings(self.home).read_bytes()
        with self.assertRaises(hi.HookInstallError):
            hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertEqual(_settings(self.home).read_bytes(), original)  # untouched
        self.assertIsNone(hi.read_sidecar(self.home))

    def test_empty_settings_treated_as_empty(self) -> None:
        _write_settings(self.home, "   \n")
        hi.install(home=self.home, checkout=ROOT, apply=True)
        self.assertEqual(hi.status(home=self.home, checkout=ROOT).overall, "OK")

    # ── COLLISION: managed basename outside allowlisted roots ─────────
    def test_collision_not_mutated(self) -> None:
        bad = 'py "D:/somewhere/else/answer_footer.py"'
        _write_settings(self.home, {"hooks": {"Stop": [
            {"matcher": "*", "hooks": [{"type": "command", "command": bad}]},
        ]}})
        res = hi.install(home=self.home, checkout=ROOT, apply=False)
        self.assertTrue(any("answer_footer.py" in c for c in res["collisions"]))

    # ── formatter round-trip still OK (structural detection, B5) ──────
    def test_formatter_roundtrip_reports_ok(self) -> None:
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        # reformat: different indent + reversed event key order
        reordered = {"hooks": dict(reversed(list(settings["hooks"].items())))}
        _settings(self.home).write_text(json.dumps(reordered, separators=(",", ":")), encoding="utf-8")
        self.assertEqual(hi.status(home=self.home, checkout=ROOT).overall, "OK")

    # ── crash between writes -> INCOMPLETE_INSTALL ────────────────────
    def test_pending_sidecar_reports_incomplete(self) -> None:
        hi.install(home=self.home, checkout=ROOT, apply=True)
        sc = hi.read_sidecar(self.home)
        sc["state"] = "pending"
        hi.write_sidecar(self.home, sc)
        self.assertEqual(hi.status(home=self.home, checkout=ROOT).overall, "INCOMPLETE_INSTALL")

    # ── uninstall is surgical ─────────────────────────────────────────
    def test_uninstall_removes_only_owned(self) -> None:
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        settings["hooks"].setdefault("Stop", []).append(
            {"matcher": "*", "hooks": [{"type": "command", "command": 'py "X:/foreign.py"'}]})
        _settings(self.home).write_text(json.dumps(settings), encoding="utf-8")
        hi.uninstall(home=self.home, apply=True)
        after = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        all_cmds = [h["command"] for groups in after.get("hooks", {}).values()
                    for g in groups for h in g["hooks"]]
        self.assertIn('py "X:/foreign.py"', all_cmds)   # foreign survived
        self.assertFalse(any("session_router.py" in c for c in all_cmds))  # managed gone
        self.assertIsNone(hi.read_sidecar(self.home))    # sidecar removed

    # ── never-installed clean machine ─────────────────────────────────
    def test_never_installed_on_clean_home(self) -> None:
        rep = hi.status(home=self.home, checkout=ROOT)
        self.assertEqual(rep.overall, "NEVER_INSTALLED")
        self.assertTrue(hi.block_invalidated(rep))

    # ── non-hook keys preserved ───────────────────────────────────────
    def test_non_hook_keys_preserved(self) -> None:
        _write_settings(self.home, {"env": {"FOO": "bar"}, "permissions": {"allow": ["x"]}})
        hi.install(home=self.home, checkout=ROOT, apply=True)
        settings = json.loads(_settings(self.home).read_text(encoding="utf-8"))
        self.assertEqual(settings["env"], {"FOO": "bar"})
        self.assertEqual(settings["permissions"], {"allow": ["x"]})


class UnresolvedPathTests(unittest.TestCase):
    """Isolated fake checkout so a managed script can be genuinely missing."""

    def test_unresolved_path_when_script_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "repo"
            (checkout / ".git").mkdir(parents=True)
            (checkout / "scripts").mkdir()
            (checkout / "templates").mkdir()
            (checkout / "scripts" / "present.py").write_text("# present\n", encoding="utf-8")
            manifest = {"schema_version": hi.MANIFEST_SCHEMA, "entries": [
                {"event": "Stop", "matcher": "*", "script": "present.py", "interpreter": "python", "timeout": 5},
                {"event": "Stop", "matcher": "*", "script": "absent.py", "interpreter": "python", "timeout": 5},
            ]}
            (checkout / "templates" / "hooks.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            home = Path(tmp) / "home"
            (home / ".claude").mkdir(parents=True)
            rep = hi.status(home=home, checkout=checkout)
            verdicts = {e.script: e.verdict for e in rep.entries}
            self.assertEqual(verdicts.get("absent.py"), "UNRESOLVED_PATH")
            self.assertTrue(hi.block_invalidated(rep))
            # install must fail closed, no write
            with self.assertRaises(hi.HookInstallError):
                hi.install(home=home, checkout=checkout, apply=True)
            self.assertFalse((home / ".claude" / "settings.json").exists())


class TierBImportTests(unittest.TestCase):
    """Regression guard (Matrix B7 note): Tier-B scripts import repo siblings via
    CPython sys.path[0]; prove the managed scripts import from the repo scripts dir."""

    def test_session_router_imports_from_scripts_dir(self) -> None:
        code = "import session_router, session_lifecycle; print('ok')"
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(Path(tempfile.gettempdir())),
                              env={"PYTHONPATH": str(ROOT / "scripts"), **_min_env()},
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)


def _min_env() -> dict:
    import os
    keep = {"PATH", "SYSTEMROOT", "PATHEXT", "TEMP", "TMP", "WINDIR"}
    return {k: v for k, v in os.environ.items() if k in keep}


if __name__ == "__main__":
    unittest.main()
