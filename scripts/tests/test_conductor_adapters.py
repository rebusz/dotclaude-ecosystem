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

    # Install
    res_inst = install(root_dir=inst_root)
    assert res_inst["status"] == "INSTALLED"

    # Check
    res_check = check_status(root_dir=inst_root)
    assert res_check["status"] == "INSTALLED"

    # Uninstall
    res_uninst = uninstall(root_dir=inst_root)
    assert res_uninst["status"] == "UNINSTALLED"
