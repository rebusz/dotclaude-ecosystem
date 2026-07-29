"""TruthDeck-style installer for TruthDeck Conductor.

Manages ~/.conductor installation, status.json metadata, backups, and clean uninstall.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import time
from typing import Any, Dict, Optional

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_model import current_utc_iso  # noqa: E402
from scripts.conductor_store import ConductorStore, get_default_conductor_dir  # noqa: E402


def compute_file_hash(filepath: pathlib.Path) -> str:
    """Compute SHA-256 hash of file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def install(root_dir: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    store = ConductorStore(root_dir=root_dir)
    status_file = store.root_dir / "status.json"
    bin_dir = store.root_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    python_exe = sys.executable

    for tool_name, script_name in [
        ("conductorctl", "conductorctl.py"),
        ("conductord", "conductord.py"),
        ("conductor_mcp", "conductor_mcp.py"),
        ("conductor_install", "conductor_install.py"),
    ]:
        script_path = (repo_root / "scripts" / script_name).resolve()

        # Windows CMD shim
        cmd_shim = bin_dir / f"{tool_name}.cmd"
        cmd_shim.write_text(f'@echo off\n"{python_exe}" "{script_path}" %*\n', encoding="utf-8")

        # Shell shim
        sh_shim = bin_dir / tool_name
        sh_shim.write_text(f'#!/bin/sh\nexec "{python_exe}" "{script_path}" "$@"\n', encoding="utf-8")
        try:
            sh_shim.chmod(0o755)
        except Exception:
            pass

    file_hashes = {}
    for script_file in (repo_root / "scripts").glob("*.py"):
        file_hashes[script_file.name] = compute_file_hash(script_file)

    status_data = {
        "status": "INSTALLED",
        "version": "1.0.0",
        "installed_at_utc": current_utc_iso(),
        "root_dir": str(store.root_dir),
        "bin_dir": str(bin_dir),
        "db_path": str(store.db_path),
        "file_hashes": file_hashes,
    }

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    return status_data


def check_status(root_dir: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    target_dir = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    status_file = target_dir / "status.json"

    if not status_file.exists():
        return {"status": "NOT_INSTALLED", "root_dir": str(target_dir), "db_exists": (target_dir / "conductor.db").exists()}

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["db_exists"] = (target_dir / "conductor.db").exists()
            return data
    except Exception:
        return {"status": "CORRUPT", "root_dir": str(target_dir)}


def uninstall(root_dir: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    target_dir = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    if target_dir.exists():
        backup_dir = target_dir.parent / f".conductor_uninstall_backup_{int(time.time())}"
        shutil.move(str(target_dir), str(backup_dir))
        return {"status": "UNINSTALLED", "backup_location": str(backup_dir)}
    return {"status": "NOT_INSTALLED"}


def main() -> None:
    parser = argparse.ArgumentParser(description="TruthDeck Conductor Installer")
    parser.add_argument("--check", action="store_true", help="Check installation status")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall Conductor")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    if args.check:
        res = check_status()
    elif args.uninstall:
        res = uninstall()
    else:
        res = install()

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        for k, v in res.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
