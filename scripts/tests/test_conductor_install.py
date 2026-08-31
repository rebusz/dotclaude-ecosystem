"""Tests for TruthDeck Conductor installer and conductor_gui shim generation."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import pytest

from scripts.conductor_install import (
    TOOL_SCRIPTS,
    check_status,
    compute_file_hash,
    install,
)


def test_tool_scripts_contains_conductor_gui():
    assert "conductor_gui" in TOOL_SCRIPTS
    assert TOOL_SCRIPTS["conductor_gui"] == "conductor_gui.py"


def test_install_generates_conductor_gui_shims_and_manifest_entries(tmp_path: pathlib.Path):
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    conductor_root = home_dir / ".conductor"

    manifest = install(home=home_dir)

    assert "conductor_gui" in manifest["canonical_commands"]
    assert "conductor_gui" in manifest["shims"]

    cmd_shim = conductor_root / "bin" / "conductor_gui.cmd"
    posix_shim = conductor_root / "bin" / "conductor_gui"
    assert cmd_shim.exists()
    assert posix_shim.exists()

    installed_gui = conductor_root / "app" / "scripts" / "conductor_gui.py"
    assert installed_gui.exists()

    source_gui = pathlib.Path(__file__).resolve().parent.parent / "conductor_gui.py"
    assert compute_file_hash(installed_gui) == compute_file_hash(source_gui)

    status = check_status(home=home_dir)
    assert status["state"] == "INSTALLED"
