from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_install import InstallError, install, status, uninstall  # noqa: E402


class InstallerTests(unittest.TestCase):
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
            self.assertIn("mcp_servers.keep", (home / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertIn("truthdeck", json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"])
            uninstall(home=home)
            self.assertIn("keep", json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"])


if __name__ == "__main__":
    unittest.main()
