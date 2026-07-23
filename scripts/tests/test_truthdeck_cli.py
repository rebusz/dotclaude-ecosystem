from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "truthctl.py"
REGISTRY = ROOT / "templates" / "truthdeck.registry.json.template"


def git(repo, *args):
    return subprocess.run(("git", "-C", str(repo), *args), check=True, capture_output=True, text=True).stdout.strip()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "plan.md").write_text("---\nrisk: R1\nstatus: in-progress\n---\n# Plan\n", encoding="utf-8")
        git(self.repo, "add", "plan.md")
        git(self.repo, "commit", "-m", "base")

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        return subprocess.run((sys.executable, str(CLI), *map(str, args)), capture_output=True, text=True)

    def test_snapshot_json_and_exit_contract(self):
        result = self.run_cli("snapshot", "--repo", self.repo, "--plan", "plan.md", "--registry", REGISTRY,
                              "--profile", "generic", "--require", "planned,implemented,runtime_proven", "--no-store", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = json.loads(result.stdout)
        self.assertEqual(raw["schema_version"], "truthdeck.snapshot.v1")
        self.assertEqual({x["state"] for x in raw["gates"] if x["stage"] == "runtime_proven"}, {"NOT_APPLICABLE"})

    def test_missing_review_is_unknown(self):
        result = self.run_cli("snapshot", "--repo", self.repo, "--plan", "plan.md", "--registry", REGISTRY,
                              "--profile", "generic", "--require", "exact_head_reviewed", "--no-store")
        self.assertEqual(result.returncode, 12)
        self.assertIn("UNKNOWN", result.stdout)

    def test_path_escape_is_boundary_refusal(self):
        outside = self.repo.parent / "outside-plan.md"
        outside.write_text("---\nrisk: R1\nstatus: ready\n---\n", encoding="utf-8")
        try:
            result = self.run_cli("snapshot", "--repo", self.repo, "--plan", outside, "--registry", REGISTRY, "--no-store")
            self.assertEqual(result.returncode, 3)
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
