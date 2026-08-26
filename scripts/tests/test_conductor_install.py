from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.conductor_install import MANIFEST_SCHEMA, check_status, install
from scripts.conductor_store import ConductorStore


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MANIFEST_KEYS = {
    "schema_version",
    "files",
    "source_head_sha",
    "source_tree_sha256",
    "interpreter",
    "canonical_commands",
    "shims",
}


def test_state_store_without_manifest_is_not_an_installed_command_owner(tmp_path):
    root = tmp_path / ".conductor"
    ConductorStore(root_dir=root).close()

    status = check_status(home=tmp_path)

    assert status["state"] == "ABSENT"
    assert status["db_exists"] is True
    assert status["leader_active"] is False
    assert Path(status["manifest"]) == root / "install-manifest.json"
    assert (root / "install-manifest.json").exists() is False


def test_absent_status_is_read_only(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    status = check_status(home=home)

    assert status["state"] == "ABSENT"
    assert status["db_exists"] is False
    assert (home / ".conductor").exists() is False


def test_install_writes_canonical_owned_manifest_to_temp_home(tmp_path):
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

    assert status["state"] == "INVALID_MANIFEST"


def test_owned_script_digest_drift_is_detected(tmp_path):
    home = (tmp_path / "home").resolve()
    home.mkdir()
    install(repo_root=REPO_ROOT, home=home)
    conductorctl = home / ".conductor" / "app" / "scripts" / "conductorctl.py"
    relative_conductorctl = str(conductorctl.relative_to(home))
    conductorctl.write_text("# drift\n", encoding="utf-8")

    status = check_status(home=home)

    assert status["state"] == "DRIFTED"
    assert relative_conductorctl in status["drift"]


def test_top_level_installers_require_explicit_conductor_opt_in():
    powershell = (REPO_ROOT / "install" / "install.ps1").read_text(encoding="utf-8")
    posix = (REPO_ROOT / "install" / "install.sh").read_text(encoding="utf-8")

    ps_guard = powershell.index("if ($InstallConductor)")
    ps_install = powershell.index("& py $ConductorInstaller install", ps_guard)
    ps_else = powershell.index("} else {", ps_guard)
    ps_status = powershell.index("& py $ConductorInstaller status", ps_else)
    assert "[switch]$InstallConductor" in powershell
    assert ps_guard < ps_install < ps_else < ps_status

    sh_guard = posix.index('if [ "$INSTALL_CONDUCTOR" -eq 1 ]; then')
    sh_install = posix.index('python3 "$CONDUCTOR_INSTALLER" install', sh_guard)
    sh_else = posix.index("\nelse\n", sh_guard)
    sh_status = posix.index('python3 "$CONDUCTOR_INSTALLER" status', sh_else)
    assert '"--install-conductor"' in posix
    assert sh_guard < sh_install < sh_else < sh_status
