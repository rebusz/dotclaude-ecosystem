from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import install_cursor_session_lifecycle as ics  # noqa: E402

ADAPTER = ROOT / "scripts" / "cursor_session_adapter.py"
TEMPLATE = ROOT / "templates" / "cursor_hooks.json.template"


class InstallCursorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.hooks_path = self.home / ".cursor" / "hooks.json"
        self.backup_root = self.home / ".cursor" / "backups"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self) -> ics.InstallResult:
        return ics.install(
            hooks_path=self.hooks_path,
            hooks_template_path=TEMPLATE,
            adapter_path=ADAPTER,
            python_executable=Path(sys.executable),
            backup_root=self.backup_root,
        )

    # ── fresh ──────────────────────────────────────────────────────────
    def test_fresh_install_creates_flat_schema_with_both_events(self) -> None:
        result = self._install()
        self.assertTrue(result.changed)
        data = json.loads(self.hooks_path.read_bytes())
        self.assertEqual(data["version"], 1)
        for event in ("sessionStart", "sessionEnd"):
            handlers = data["hooks"][event]
            self.assertEqual(len(handlers), 1)
            self.assertIn("cursor_session_adapter.py", handlers[0]["command"])
            self.assertNotIn("commandWindows", handlers[0])  # not a documented Cursor field
        self.assertNotIn("preCompact", data["hooks"])  # deliberately out of CU3 scope

    def test_no_matcher_on_session_events(self) -> None:
        self._install()
        data = json.loads(self.hooks_path.read_bytes())
        for event in ("sessionStart", "sessionEnd"):
            self.assertNotIn("matcher", data["hooks"][event][0])

    # ── repeat (idempotent no-op) ──────────────────────────────────────
    def test_repeat_install_is_semantic_noop(self) -> None:
        self._install()
        before = self.hooks_path.read_bytes()
        second = self._install()
        self.assertFalse(second.changed)
        self.assertIsNone(second.manifest_path)
        self.assertEqual(self.hooks_path.read_bytes(), before)

    # ── conflict (foreign content preserved) ───────────────────────────
    def test_foreign_event_and_foreign_handler_preserved_across_install(self) -> None:
        self.hooks_path.parent.mkdir(parents=True)
        self.hooks_path.write_text(json.dumps({
            "version": 1,
            "hooks": {
                "beforeShellExecution": [{"command": ".cursor/hooks/approve.sh", "matcher": "curl"}],
                "sessionStart": [{"command": "py foreign_start.py"}],
            },
        }), encoding="utf-8")
        self._install()
        data = json.loads(self.hooks_path.read_bytes())
        self.assertEqual(data["hooks"]["beforeShellExecution"],
                         [{"command": ".cursor/hooks/approve.sh", "matcher": "curl"}])
        start_cmds = [h["command"] for h in data["hooks"]["sessionStart"]]
        self.assertIn("py foreign_start.py", start_cmds)
        self.assertEqual(sum("cursor_session_adapter.py" in c for c in start_cmds), 1)

    def test_reinstall_after_hand_edit_does_not_duplicate_owned_handler(self) -> None:
        self._install()
        data = json.loads(self.hooks_path.read_bytes())
        data["hooks"]["sessionStart"].append({"command": "py another_foreign.py"})
        self.hooks_path.write_bytes((json.dumps(data) + "\n").encode("utf-8"))
        self._install()
        data2 = json.loads(self.hooks_path.read_bytes())
        cmds = [h["command"] for h in data2["hooks"]["sessionStart"]]
        self.assertEqual(sum("cursor_session_adapter.py" in c for c in cmds), 1)
        self.assertIn("py another_foreign.py", cmds)

    def test_unsupported_version_fails_closed(self) -> None:
        self.hooks_path.parent.mkdir(parents=True)
        self.hooks_path.write_text(json.dumps({"version": 2, "hooks": {}}), encoding="utf-8")
        before = self.hooks_path.read_bytes()
        with self.assertRaises(ValueError):
            self._install()
        self.assertEqual(self.hooks_path.read_bytes(), before)  # untouched

    def test_malformed_existing_hooks_fails_closed(self) -> None:
        self.hooks_path.parent.mkdir(parents=True)
        self.hooks_path.write_text("not json at all", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self._install()

    # ── interruption / containment ─────────────────────────────────────
    def test_rollback_refuses_manifest_outside_backup_root(self) -> None:
        result = self._install()
        outside = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            ics.rollback(result.manifest_path, allowed_backup_root=outside,
                        expected_hooks_path=self.hooks_path)

    def test_rollback_refuses_wrong_expected_path(self) -> None:
        result = self._install()
        with self.assertRaises(ValueError):
            ics.rollback(result.manifest_path, allowed_backup_root=self.backup_root,
                        expected_hooks_path=Path(tempfile.mkdtemp()) / "hooks.json")

    def test_rollback_refuses_when_target_changed_since_install(self) -> None:
        result = self._install()
        self.hooks_path.write_bytes(b'{"version":1,"hooks":{}}')
        with self.assertRaises(ValueError):
            ics.rollback(result.manifest_path, allowed_backup_root=self.backup_root,
                        expected_hooks_path=self.hooks_path)

    def test_install_restores_pre_image_on_write_failure(self) -> None:
        # Simulate a crash between backup and manifest write by making the manifest
        # directory read-only after backup but before the manifest is written --
        # instead, directly exercise _restore_if_installed's failure path via a
        # forced exception injected through a monkeypatched _encoded.
        self.hooks_path.parent.mkdir(parents=True)
        self.hooks_path.write_bytes(b'{"version":1,"hooks":{}}')
        orig = ics._encoded
        calls = {"n": 0}

        def boom(value):
            calls["n"] += 1
            if calls["n"] == 2:  # first call renders hooks_bytes ok; second is the manifest
                raise RuntimeError("simulated crash")
            return orig(value)
        ics._encoded = boom
        try:
            with self.assertRaises(RuntimeError):
                self._install()
        finally:
            ics._encoded = orig
        # target must be restored to its pre-crash content
        self.assertEqual(self.hooks_path.read_bytes(), b'{"version":1,"hooks":{}}')

    # ── rollback happy path ─────────────────────────────────────────────
    def test_rollback_restores_exact_pre_image(self) -> None:
        self.hooks_path.parent.mkdir(parents=True)
        pre = json.dumps({"version": 1, "hooks": {"stop": [{"command": "py x.py"}]}})
        self.hooks_path.write_text(pre, encoding="utf-8")
        result = self._install()
        ics.rollback(result.manifest_path, allowed_backup_root=self.backup_root,
                    expected_hooks_path=self.hooks_path)
        self.assertEqual(self.hooks_path.read_text(encoding="utf-8"), pre)

    def test_rollback_of_fresh_install_removes_file(self) -> None:
        result = self._install()
        self.assertTrue(self.hooks_path.exists())
        ics.rollback(result.manifest_path, allowed_backup_root=self.backup_root,
                    expected_hooks_path=self.hooks_path)
        self.assertFalse(self.hooks_path.exists())

    # ── CLI dry-run purity ───────────────────────────────────────────────
    def test_cli_dry_run_writes_nothing(self) -> None:
        import subprocess
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "install_cursor_session_lifecycle.py"),
             "--hooks-path", str(self.hooks_path), "--backup-root", str(self.backup_root)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["mode"], "dry-run")
        self.assertFalse(self.hooks_path.exists())


if __name__ == "__main__":
    unittest.main()
