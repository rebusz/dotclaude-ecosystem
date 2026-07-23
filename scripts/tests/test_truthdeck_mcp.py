from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_mcp import create_server  # noqa: E402
from truthctl import build_snapshot  # noqa: E402


class McpTests(unittest.TestCase):
    def test_exposes_exactly_four_static_tools(self):
        server = create_server()
        names = set(server._tool_manager._tools)  # SDK v1 stable inspection contract
        self.assertEqual(names, {"truthdeck_snapshot", "truthdeck_next", "truthdeck_verify_handoff", "truthdeck_diff"})

    def test_snapshot_tool_has_cli_core_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(("git", "-C", str(repo), "init", "-b", "main"), check=True, capture_output=True)
            subprocess.run(("git", "-C", str(repo), "config", "user.email", "test@example.com"), check=True)
            subprocess.run(("git", "-C", str(repo), "config", "user.name", "Test"), check=True)
            plan = repo / "plan.md"
            plan.write_text("---\nrisk: R1\nstatus: in-progress\n---\n", encoding="utf-8")
            subprocess.run(("git", "-C", str(repo), "add", "plan.md"), check=True)
            subprocess.run(("git", "-C", str(repo), "commit", "-m", "base"), check=True, capture_output=True)
            registry = ROOT / "templates" / "truthdeck.registry.json.template"
            mcp_raw = create_server()._tool_manager._tools["truthdeck_snapshot"].fn(
                str(repo), str(registry), str(plan), None, "generic"
            )
            cli_snapshot = build_snapshot(repos=[repo], registry_path=registry, plan=plan, profile_name="generic")
            self.assertEqual(mcp_raw["snapshot_id"], cli_snapshot.snapshot_id)


if __name__ == "__main__":
    unittest.main()
