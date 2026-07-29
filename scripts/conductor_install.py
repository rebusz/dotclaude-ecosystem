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
import time
from typing import Any, Dict, Optional

from scripts.conductor_model import current_utc_iso
from scripts.conductor_store import ConductorStore, get_default_conductor_dir


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

    file_hashes = {}
    repo_root = pathlib.Path(__file__).parent.parent
    for script_name in [
        "conductor_model.py",
        "conductor_store.py",
        "conductor_commands.py",
        "conductor_discovery.py",
        "conductor_scheduler.py",
        "conductor_repo.py",
        "conductor_truthdeck.py",
        "conductor_workflow.py",
        "conductorctl.py",
        "conductord.py",
        "conductor_mcp.py",
        "conductor_adapters.py",
        "conductor_install.py",
    ]:
        p = repo_root / "scripts" / script_name
        if p.exists():
            file_hashes[script_name] = compute_file_hash(p)

    status_data = {
        "status": "INSTALLED",
        "version": "1.0.0",
        "installed_at_utc": current_utc_iso(),
        "root_dir": str(store.root_dir),
        "db_path": str(store.db_path),
        "file_hashes": file_hashes,
    }

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    return status_data


def check_status(root_dir: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    store = ConductorStore(root_dir=root_dir)
    status_file = store.root_dir / "status.json"

    if not status_file.exists():
        return {"status": "NOT_INSTALLED", "root_dir": str(store.root_dir)}

    with open(status_file, "r", encoding="utf-8") as f:
        return json.load(f)


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
