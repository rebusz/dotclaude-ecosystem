"""Unit tests for ConductorHostRegistry, installer, and host adapters."""

import pathlib

from scripts.conductor_adapters import ConductorHostRegistry, HostClassification
from scripts.conductor_install import check_status, install, uninstall


def test_host_registry_doctor():
    report = ConductorHostRegistry.doctor_report()
    assert "claude_code" in report
    assert "antigravity_ide" in report
    assert "agy_cli" in report

    # agy CLI should be HOLD_NOT_INSTALLED
    assert report["agy_cli"]["cooperative_client"] == HostClassification.HOLD_NOT_INSTALLED

    # Antigravity IDE should classify correctly
    antigrav_spec = report["antigravity_ide"]
    assert antigrav_spec["host_key"] == "antigravity_ide"


def test_installer_lifecycle(tmp_path: pathlib.Path):
    inst_root = tmp_path / ".conductor_test_install"

    # 1. Read-only check_status on non-existent directory must NOT create directory or DB
    non_existent = tmp_path / ".conductor_non_existent"
    st_none = check_status(root_dir=non_existent)
    assert st_none["status"] == "NOT_INSTALLED"
    assert not non_existent.exists()

    # 2. Install
    res_inst = install(root_dir=inst_root)
    assert res_inst["status"] == "INSTALLED"
    bin_dir = pathlib.Path(res_inst["bin_dir"])
    assert bin_dir.exists()
    assert (bin_dir / "conductorctl.cmd").exists()
    assert (bin_dir / "conductorctl").exists()

    # 3. Check installed status
    res_check = check_status(root_dir=inst_root)
    assert res_check["status"] == "INSTALLED"
    assert res_check["db_exists"] is True

    # 4. Uninstall
    res_uninst = uninstall(root_dir=inst_root)
    assert res_uninst["status"] == "UNINSTALLED"
