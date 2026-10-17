"""The taste lockfile is validated before any value reaches git, npx or rm -rf
(audit P2-19/P2-20)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "install" / "taste_lock.py"
LOCK = ROOT / "skills" / "taste-skill.lock.json"


def _run(lock: Path, field: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VALIDATOR), str(lock), field],
                          capture_output=True, text=True, check=False)


def test_the_committed_lockfile_is_valid_and_pinned() -> None:
    assert _run(LOCK, "commit").stdout.strip() == json.loads(LOCK.read_text("utf-8"))["pinned_commit"]
    cli = _run(LOCK, "cli")
    assert cli.returncode == 0 and "@" in cli.stdout


@pytest.mark.parametrize("key,value", [
    ("source", "--upload-pack=touch /tmp/pwned"),
    ("source", "ext::sh -c touch% /tmp/pwned"),
    ("source", "file:///etc"),
    ("pinned_commit", "main"),
    ("pinned_commit", "--orphan=x"),
    ("cli_package", "skills"),
    ("cli_package", "skills@latest"),
    ("cli_package", "skills@^1.5.0"),
    ("installed", ["../../.."]),
    ("installed", ["-rf"]),
    ("installed", ["ok", "a/b"]),
    ("agents", ["claude code"]),
    ("installed", []),
])
def test_a_hostile_value_is_rejected(tmp_path: Path, key: str, value: object) -> None:
    lock = json.loads(LOCK.read_text("utf-8"))
    lock[key] = value
    bad = tmp_path / "lock.json"
    bad.write_text(json.dumps(lock), encoding="utf-8")
    for field in ("source", "commit", "cli", "installed", "agents"):
        cp = _run(bad, field)
        assert cp.returncode == 2, (field, cp.stdout)
        assert cp.stdout == ""  # nothing for the installer to consume


@pytest.mark.parametrize("name", ["install_taste_skills.sh", "install_taste_skills.ps1"])
def test_both_installers_read_only_through_the_validator(name: str) -> None:
    text = (ROOT / "install" / name).read_text(encoding="utf-8")
    assert "taste_lock.py" in text
    assert "json.load" not in text and "ConvertFrom-Json" not in text
    assert "clone --quiet -- " in text
    assert "--detach" in text
    assert "npx --yes skills" not in text  # the CLI version comes from the lockfile


def test_the_overlay_pins_code_review_graph() -> None:
    text = (ROOT / "agent-rules" / "overlays" / "claude-global.md").read_text(encoding="utf-8")
    assert "uvx code-review-graph " not in text
    assert "uvx code-review-graph@" in text
