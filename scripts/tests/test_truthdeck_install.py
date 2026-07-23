from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_install import InstallError, _shim_spec, install, status, uninstall  # noqa: E402


class InstallerTests(unittest.TestCase):
    def test_ci_runs_once_when_draft_becomes_ready(self):
        workflow = (ROOT / ".github" / "workflows" / "truthdeck-ci.yml").read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize, reopened, ready_for_review]", workflow)
        self.assertIn("if: github.event.pull_request.draft == false", workflow)

    def test_install_status_idempotency_and_uninstall_preserve_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            user_bin = home / "bin"
            user_bin.mkdir()
            first = install(repo_root=ROOT, home=home, path_value=str(user_bin))
            second = install(repo_root=ROOT, home=home, path_value=str(user_bin))
            self.assertEqual(first["path_state"], "PASS")
            self.assertEqual(second["state"], "installed")
            self.assertEqual(status(home=home)["state"], "installed")
            self.assertTrue((home / ".codex" / "skills" / "truthdeck" / "SKILL.md").exists())
            self.assertTrue((home / ".claude" / "skills" / "truthdeck" / "SKILL.md").exists())
            snapshots = home / ".truthdeck" / "snapshots"
            snapshots.mkdir()
            result = uninstall(home=home)
            self.assertTrue(result["snapshots_preserved"])
            self.assertTrue(result["registry_preserved"])

    def test_uninstall_refuses_owned_file_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install(repo_root=ROOT, home=home, path_value="")
            target = home / ".truthdeck" / "bin" / "truthctl.py"
            target.write_text("changed", encoding="utf-8")
            with self.assertRaises(InstallError):
                uninstall(home=home)

    def test_mcp_registration_preserves_foreign_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".codex").mkdir()
            (home / ".codex" / "config.toml").write_text('[mcp_servers.keep]\ncommand="keep"\n', encoding="utf-8")
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {"keep": {"command": "keep"}}}), encoding="utf-8")
            install(repo_root=ROOT, home=home, enable_mcp="both", path_value="")
            readback = status(home=home)
            self.assertTrue(readback["cli_installed"])
            self.assertTrue(readback["codex_skill_installed"])
            self.assertTrue(readback["claude_skill_installed"])
            self.assertTrue(readback["mcp_codex_active"])
            self.assertTrue(readback["mcp_claude_active"])
            self.assertIn("mcp_servers.keep", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertIn("truthdeck", json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"])
            uninstall(home=home)
            self.assertIn("keep", json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"])

    def test_foreign_shim_and_manifest_traversal_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            user_bin = home / "bin"
            user_bin.mkdir()
            shim = user_bin / "truthctl.cmd"
            shim.write_text("foreign", encoding="utf-8")
            with self.assertRaises(InstallError):
                install(repo_root=ROOT, home=home, path_value=str(user_bin))
            self.assertEqual(shim.read_text(encoding="utf-8"), "foreign")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install(repo_root=ROOT, home=home, path_value="")
            manifest_path = home / ".truthdeck" / "install-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["../victim"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(status(home=home)["state"], "invalid_manifest")
            with self.assertRaises(InstallError):
                uninstall(home=home)

    def test_partial_failure_rolls_back_and_mode_transition_removes_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {"truthdeck": {"command": "foreign"}}}), encoding="utf-8")
            with self.assertRaises(InstallError):
                install(repo_root=ROOT, home=home, enable_mcp="both", path_value="")
            self.assertFalse((home / ".truthdeck" / "install-manifest.json").exists())
            self.assertFalse((home / ".truthdeck" / "bin" / "truthctl.py").exists())
            self.assertNotIn("TRUTHDECK OWNED", (home / ".codex" / "config.toml").read_text(encoding="utf-8") if (home / ".codex" / "config.toml").exists() else "")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            install(repo_root=ROOT, home=home, enable_mcp="codex", path_value="")
            install(repo_root=ROOT, home=home, enable_mcp="none", path_value="")
            self.assertNotIn("TRUTHDECK OWNED", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))
            uninstall(home=home)

    def test_posix_shim_contract(self):
        name, payload = _shim_spec("/usr/bin/python3", Path("/opt/truthctl.py"), "posix")
        self.assertEqual(name, "truthctl")
        self.assertTrue(payload.startswith(b"#!/bin/sh\n"))
        self.assertIn(b'"$@"', payload)

    def test_shim_prefers_durable_path_and_migrates_owned_old_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ephemeral = home / ".codex" / "tmp" / "arg0" / "session"
            durable = home / ".local" / "bin"
            old_bin = home / "bin"
            for directory in (ephemeral, durable, old_bin):
                directory.mkdir(parents=True)
            first = install(repo_root=ROOT, home=home, path_value=str(old_bin))
            old_shim = Path(first["shim"])
            self.assertTrue(old_shim.exists())
            migrated = install(
                repo_root=ROOT, home=home,
                path_value=os.pathsep.join((str(ephemeral), str(durable), str(old_bin))),
            )
            shim_name, _ = _shim_spec(sys.executable, Path("truthctl.py"), os.name)
            self.assertEqual(Path(migrated["shim"]), durable / shim_name)
            self.assertFalse(old_shim.exists())
            self.assertTrue((durable / shim_name).exists())

    def test_ephemeral_home_path_does_not_receive_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ephemeral = home / ".codex" / "tmp" / "arg0" / "session"
            ephemeral.mkdir(parents=True)
            result = install(repo_root=ROOT, home=home, path_value=str(ephemeral))
            self.assertIsNone(result["shim"])
            self.assertEqual(result["path_state"], "HOLD")

    def test_durable_path_entry_normalizes_quotes_and_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            durable = home / ".local" / "bin"
            durable.mkdir(parents=True)
            result = install(repo_root=ROOT, home=home, path_value=f'  "{durable}"  ')
            self.assertEqual(result["path_state"], "PASS")


if __name__ == "__main__":
    unittest.main()
