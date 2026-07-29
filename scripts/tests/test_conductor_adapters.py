"""Unit tests for Conductor host adapters and ownership-clean installation."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from scripts.conductor_adapters import ConductorHostRegistry, HostClassification
from scripts.conductor_install import InstallError, check_status, install, uninstall
from scripts.conductor_store import ConductorStore

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_host_registry_doctor():
    report = ConductorHostRegistry.doctor_report()
    assert "claude_code" in report
    assert "antigravity_ide" in report
    assert "agy_cli" in report
    assert report["agy_cli"]["cooperative_client"] == HostClassification.HOLD_NOT_INSTALLED
    assert report["antigravity_ide"]["host_key"] == "antigravity_ide"


def test_installer_lifecycle_isolated_runtime_and_surgical_uninstall(tmp_path: pathlib.Path):
    home = tmp_path / "home"
    inst_root = home / ".conductor"

    absent = check_status(home=home, repo_root=ROOT)
    assert absent["state"] == "ABSENT"
    assert not home.exists()

    installed = install(home=home, repo_root=ROOT)
    assert installed["state"] == "INSTALLED"
    assert installed["db_exists"] is False
    assert (inst_root / "app" / "scripts" / "conductorctl.py").is_file()
    assert (inst_root / "bin" / "conductorctl.cmd").is_file()
    assert (inst_root / "bin" / "conductorctl").is_file()
    assert (home / ".codex" / "skills" / "conductor" / "SKILL.md").is_file()
    assert (home / ".claude" / "skills" / "conductor" / "SKILL.md").is_file()

    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    help_result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(inst_root / "bin" / "conductorctl.cmd"), "--help"],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "TruthDeck Conductor CTL" in help_result.stdout
    installed_status = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            str(inst_root / "bin" / "conductor_install.cmd"),
            "status",
            "--home",
            str(home),
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert installed_status.returncode == 0, installed_status.stderr
    assert json.loads(installed_status.stdout)["state"] == "INSTALLED"

    reinstalled = install(home=home, repo_root=ROOT)
    assert reinstalled["state"] == "INSTALLED"
    runtime_receipt = inst_root / "receipts" / "preserve.json"
    runtime_receipt.parent.mkdir()
    runtime_receipt.write_text("runtime evidence", encoding="utf-8")

    removed = uninstall(home=home)
    assert removed["state"] == "UNINSTALLED"
    assert runtime_receipt.read_text(encoding="utf-8") == "runtime evidence"
    assert not (inst_root / "app" / "scripts" / "conductorctl.py").exists()
    assert not (home / ".codex" / "skills" / "conductor" / "SKILL.md").exists()


def test_installer_refuses_foreign_and_drifted_owned_files(tmp_path: pathlib.Path):
    foreign_home = tmp_path / "foreign-home"
    foreign_shim = foreign_home / ".conductor" / "bin" / "conductorctl.cmd"
    foreign_shim.parent.mkdir(parents=True)
    foreign_shim.write_text("foreign", encoding="utf-8")
    with pytest.raises(InstallError, match="foreign"):
        install(home=foreign_home, repo_root=ROOT)
    assert foreign_shim.read_text(encoding="utf-8") == "foreign"
    assert not (foreign_home / ".conductor" / "install-manifest.json").exists()

    drift_home = tmp_path / "drift-home"
    install(home=drift_home, repo_root=ROOT)
    owned = drift_home / ".conductor" / "app" / "scripts" / "conductorctl.py"
    owned.write_text("drifted", encoding="utf-8")
    assert check_status(home=drift_home)["state"] == "DRIFTED"
    with pytest.raises(InstallError, match="ownership-clean"):
        install(home=drift_home, repo_root=ROOT)
    with pytest.raises(InstallError, match="not clean"):
        uninstall(home=drift_home)


def test_installer_refuses_upgrade_while_live_leader_exists(tmp_path: pathlib.Path):
    home = tmp_path / "home"
    install(home=home, repo_root=ROOT)
    store = ConductorStore(root_dir=home / ".conductor")
    assert store.acquire_leader_lock()

    with pytest.raises(InstallError, match="active Conductor leader"):
        install(home=home, repo_root=ROOT)


def test_installer_rejects_manifest_traversal_without_touching_victim(tmp_path: pathlib.Path):
    home = tmp_path / "home"
    install(home=home, repo_root=ROOT)
    victim = home / "victim.txt"
    victim.write_text("preserve", encoding="utf-8")
    manifest_path = home / ".conductor" / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../victim.txt"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert check_status(home=home)["state"] == "INVALID_MANIFEST"
    with pytest.raises(InstallError, match="escapes"):
        uninstall(home=home)
    assert victim.read_text(encoding="utf-8") == "preserve"


def test_installer_refuses_skill_target_through_symlink(tmp_path: pathlib.Path):
    home = tmp_path / "home"
    foreign = home / "foreign-skill"
    foreign.mkdir(parents=True)
    link = home / ".codex" / "skills" / "conductor"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(foreign, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(InstallError, match="symlink or junction"):
        install(home=home, repo_root=ROOT)
    assert not (foreign / "SKILL.md").exists()
    assert not (home / ".conductor" / "install-manifest.json").exists()


def test_installer_rollback_restores_previous_clean_install(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    home = tmp_path / "home"
    install(home=home, repo_root=ROOT)
    manifest_path = home / ".conductor" / "install-manifest.json"
    before = {
        path.relative_to(home): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }

    import scripts.conductor_install as installer

    real_write_atomic = installer._write_atomic
    calls = 0

    def fail_mid_upgrade(path: pathlib.Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected installer failure")
        real_write_atomic(path, payload)

    monkeypatch.setattr(installer, "_write_atomic", fail_mid_upgrade)
    with pytest.raises(OSError, match="injected"):
        install(home=home, repo_root=ROOT)
    after = {
        path.relative_to(home): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert manifest_path.is_file()


def test_installer_entrypoint_status_is_read_only(tmp_path: pathlib.Path):
    home = tmp_path / "absent"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "conductor_install.py"),
            "status",
            "--home",
            str(home),
            "--repo-root",
            str(ROOT),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["state"] == "ABSENT"
    assert not home.exists()
