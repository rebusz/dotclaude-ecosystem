from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_git import collect_git  # noqa: E402


def git(repo, *args):
    return subprocess.run(("git", "-C", str(repo), *args), check=True, capture_output=True, text=True).stdout.strip()


class GitCollectorTests(unittest.TestCase):
    def test_collects_live_head_cleanliness_and_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "Test")
            (repo / "a.txt").write_text("a", encoding="utf-8")
            git(repo, "add", "a.txt")
            git(repo, "commit", "-m", "base")
            result = collect_git(repo, base_ref="main", observed_at_utc="2026-07-22T12:00:00Z", deadline=time.monotonic() + 5)
            values = {x.key: x.value for x in result.facts}
            self.assertTrue(values["git.clean"])
            self.assertTrue(values["git.merged"])


if __name__ == "__main__":
    unittest.main()
