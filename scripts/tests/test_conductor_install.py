"""Behavioral installer tests for conductor admission contract.

Matrix (all must pass GREEN):
  [PS-1] install.ps1 default: no manifest written, conductor dir untouched
  [PS-2] install.ps1 --InstallConductor: exactly one manifest written
  [PS-3] install.ps1 manifest schema == conductor.install.v1 with valid canonical cmd
  [PS-4] install.ps1 unknown arg: nonzero exit, no manifest
  [SH-1] install.sh default: no manifest written
  [SH-2] install.sh --install-conductor: exactly one manifest written
  [SH-3] install.sh manifest schema == conductor.install.v1 with valid canonical cmd
  [SH-4] install.sh unknown arg: nonzero exit, no manifest

  [API-1] conductor db present + manifest absent => ABSENT
  [API-2] absent home => ABSENT, no dir created
  [API-3] install writes canonical manifest with correct keys/schema/commands
  [API-4] TruthDeck schema_version => INVALID_MANIFEST (not accepted as conductor)
  [API-5] file digest drift => DRIFTED
  [GUARD] tests do not touch operator real ~/.conductor
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.conductor_install import MANIFEST_SCHEMA, check_status, install
from scripts.conductor_store import ConductorStore


REPO_ROOT = Path(__file__).resolve().parents[2]
IS_WINDOWS = platform.system() == "Windows"
IS_POSIX = not IS_WINDOWS

MANIFEST_PATH = Path.home() / ".conductor" / "install-manifest.json"

EXPECTED_MANIFEST_KEYS = {
    "schema_version",
    "files",
    "source_head_sha",
    "source_tree_sha256",
    "interpreter",
    "canonical_commands",
    "shims",
}


# ---------------------------------------------------------------------------
# Safety invariant: real operator manifest is never touched
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _guard_real_manifest():
    """Fail immediately if a test mutates the operator's live install-manifest."""
    before = MANIFEST_PATH.read_bytes() if MANIFEST_PATH.exists() else None
    yield
    after = MANIFEST_PATH.read_bytes() if MANIFEST_PATH.exists() else None
    assert before == after, (
        "SAFETY VIOLATION: real ~/.conductor/install-manifest.json was modified"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest_path(home: Path) -> Path:
    return home / ".conductor" / "install-manifest.json"


def _read_manifest(home: Path) -> dict:
    return json.loads(_manifest_path(home).read_text(encoding="utf-8"))


def _run_ps1(tmp_home: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run install.ps1 with isolated USERPROFILE."""
    ps1 = REPO_ROOT / "install" / "install.ps1"
    cmd = [
        "pwsh", "-NoProfile", "-NonInteractive",
        "-File", str(ps1),
    ] + (extra_args or [])
    env = {**os.environ, "USERPROFILE": str(tmp_home), "HOME": str(tmp_home)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def _run_sh(tmp_home: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run install.sh with isolated HOME."""
    sh = REPO_ROOT / "install" / "install.sh"
    cmd = ["bash", str(sh)] + (extra_args or [])
    env = {**os.environ, "HOME": str(tmp_home)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


# ---------------------------------------------------------------------------
# PowerShell behavioral matrix
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not IS_WINDOWS and shutil.which("pwsh") is None,
                    reason="pwsh not available on this runner")
class TestInstallPs1Behavioral:
    def test_ps1_default_creates_no_conductor_manifest(self, tmp_path):
        """[PS-1] Default invocation must not create a Conductor manifest."""
        result = _run_ps1(tmp_path)
        assert result.returncode == 0, f"install.ps1 failed:\n{result.stderr}"
        assert not _manifest_path(tmp_path).exists(), (
            "install.ps1 default run wrote a Conductor manifest \u2014 admission boundary violated"
        )

    def test_ps1_explicit_opt_in_creates_exactly_one_manifest(self, tmp_path):
        """[PS-2] Explicit -InstallConductor must produce exactly one manifest."""
        result = _run_ps1(tmp_path, ["-InstallConductor"])
        assert result.returncode == 0, f"install.ps1 -InstallConductor failed:\n{result.stderr}"
        assert _manifest_path(tmp_path).exists(), (
            "install.ps1 -InstallConductor did not write manifest"
        )
        conductor_dir = tmp_path / ".conductor"
        manifests = list(conductor_dir.glob("install-manifest*.json"))
        assert len(manifests) == 1, f"Expected exactly 1 manifest, found: {manifests}"

    def test_ps1_opt_in_manifest_has_correct_schema_and_canonical_command(self, tmp_path):
        """[PS-3] Manifest written by -InstallConductor must be conductor.install.v1."""
        result = _run_ps1(tmp_path, ["-InstallConductor"])
        assert result.returncode == 0
        manifest = _read_manifest(tmp_path)
        assert set(manifest) == EXPECTED_MANIFEST_KEYS
        assert manifest["schema_version"] == "conductor.install.v1"
        assert "conductorctl" in manifest["canonical_commands"]
        cmd = manifest["canonical_commands"]["conductorctl"]
        assert isinstance(cmd, list) and len(cmd) >= 2, (
            f"canonical_commands.conductorctl must be a [interpreter, script] list, got: {cmd}"
        )
        script_path = Path(cmd[-1])
        assert script_path.exists(), f"Canonical script path does not exist: {script_path}"

    def test_ps1_unknown_arg_returns_nonzero_and_no_manifest(self, tmp_path):
        """[PS-4] Unknown argument must return nonzero and leave no manifest."""
        result = _run_ps1(tmp_path, ["--unknown-argument-xyz"])
        assert result.returncode != 0, (
            "install.ps1 should fail on unknown argument but returned 0"
        )
        assert not _manifest_path(tmp_path).exists(), (
            "install.ps1 wrote a manifest even though invocation failed"
        )


# ---------------------------------------------------------------------------
# POSIX bash behavioral matrix
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestInstallShBehavioral:
    def test_sh_default_creates_no_conductor_manifest(self, tmp_path):
        """[SH-1] Default invocation must not create a Conductor manifest."""
        result = _run_sh(tmp_path)
        assert result.returncode == 0, f"install.sh failed:\n{result.stderr}"
        assert not _manifest_path(tmp_path).exists(), (
            "install.sh default run wrote a Conductor manifest \u2014 admission boundary violated"
        )

    def test_sh_explicit_opt_in_creates_exactly_one_manifest(self, tmp_path):
        """[SH-2] Explicit --install-conductor must produce exactly one manifest."""
        result = _run_sh(tmp_path, ["--install-conductor"])
        assert result.returncode == 0, f"install.sh --install-conductor failed:\n{result.stderr}"
        assert _manifest_path(tmp_path).exists(), (
            "install.sh --install-conductor did not write manifest"
        )
        manifests = list((tmp_path / ".conductor").glob("install-manifest*.json"))
        assert len(manifests) == 1, f"Expected exactly 1 manifest, found: {manifests}"

    def test_sh_opt_in_manifest_has_correct_schema_and_canonical_command(self, tmp_path):
        """[SH-3] Manifest written by --install-conductor must be conductor.install.v1."""
        result = _run_sh(tmp_path, ["--install-conductor"])
        assert result.returncode == 0
        manifest = _read_manifest(tmp_path)
        assert set(manifest) == EXPECTED_MANIFEST_KEYS
        assert manifest["schema_version"] == "conductor.install.v1"
        assert "conductorctl" in manifest["canonical_commands"]
        cmd = manifest["canonical_commands"]["conductorctl"]
        assert isinstance(cmd, list) and len(cmd) >= 2
        script_path = Path(cmd[-1])
        assert script_path.exists(), f"Canonical script path does not exist: {script_path}"

    def test_sh_unknown_arg_returns_nonzero_and_no_manifest(self, tmp_path):
        """[SH-4] Unknown argument must return nonzero and leave no manifest."""
        result = _run_sh(tmp_path, ["--unknown-argument-xyz"])
        assert result.returncode != 0, (
            "install.sh should fail on unknown argument but returned 0"
        )
        assert not _manifest_path(tmp_path).exists(), (
            "install.sh wrote a manifest even though invocation failed"
        )


# ---------------------------------------------------------------------------
# Python API behavioral matrix (conductor_install module)
# ---------------------------------------------------------------------------

def test_state_store_without_manifest_is_not_an_installed_command_owner(tmp_path):
    """[API-1] conductor.db exists but no manifest => ABSENT."""
    root = tmp_path / ".conductor"
    ConductorStore(root_dir=root).close()

    status = check_status(home=tmp_path)

    assert status["state"] == "ABSENT"
    assert status["db_exists"] is True
    assert status["leader_active"] is False
    assert Path(status["manifest"]) == root / "install-manifest.json"
    assert (root / "install-manifest.json").exists() is False


def test_absent_status_is_read_only(tmp_path):
    """[API-2] check_status on empty home must be ABSENT without creating any dir."""
    home = tmp_path / "home"
    home.mkdir()

    status = check_status(home=home)

    assert status["state"] == "ABSENT"
    assert status["db_exists"] is False
    assert (home / ".conductor").exists() is False


def test_install_writes_canonical_owned_manifest_to_temp_home(tmp_path):
    """[API-3] install() writes manifest with correct schema, keys, canonical commands."""
    home = (tmp_path / "home").resolve()
    home.mkdir()

    status = install(repo_root=REPO_ROOT, home=home)
    manifest_path = home / ".conductor" / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conductorctl = home / ".conductor" / "app" / "scripts" / "conductorctl.py"
    relative_conductorctl = str(conductorctl.relative_to(home))

    assert status["state"] == "INSTALLED"
    assert set(manifest) == EXPECTED_MANIFEST_KEYS
    assert manifest["schema_version"] == MANIFEST_SCHEMA == "conductor.install.v1"
    assert manifest["interpreter"] == sys.executable
    assert manifest["canonical_commands"]["conductorctl"] == [
        sys.executable,
        str(conductorctl),
    ]
    assert set(manifest["canonical_commands"]) == {
        "conductorctl",
        "conductord",
        "conductor_mcp",
        "conductor_install",
    }
    assert manifest["files"][relative_conductorctl] == hashlib.sha256(
        conductorctl.read_bytes()
    ).hexdigest()


def test_truthdeck_manifest_is_not_accepted_as_conductor_install(tmp_path):
    """[API-4] TruthDeck schema_version must not satisfy Conductor admission."""
    root = tmp_path / ".conductor"
    root.mkdir()
    manifest_path = root / "install-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "truthdeck.install.v1",
                "files": {},
                "source_head_sha": "0" * 40,
                "source_tree_sha256": "0" * 64,
                "interpreter": sys.executable,
                "canonical_commands": {},
                "shims": {},
            }
        ),
        encoding="utf-8",
    )

    status = check_status(home=tmp_path)

    assert status["state"] == "INVALID_MANIFEST", (
        "TruthDeck manifest must not be accepted as a valid Conductor install"
    )


def test_owned_script_digest_drift_is_detected(tmp_path):
    """[API-5] File digest drift after install must be detected as DRIFTED."""
    home = (tmp_path / "home").resolve()
    home.mkdir()
    install(repo_root=REPO_ROOT, home=home)
    conductorctl = home / ".conductor" / "app" / "scripts" / "conductorctl.py"
    relative_conductorctl = str(conductorctl.relative_to(home))
    conductorctl.write_text("# drift\n", encoding="utf-8")

    status = check_status(home=home)

    assert status["state"] == "DRIFTED"
    assert relative_conductorctl in status["drift"]
