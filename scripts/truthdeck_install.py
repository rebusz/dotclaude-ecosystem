"""Surgical ownership-checked TruthDeck installer, status, and uninstaller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "truthdeck.install.v1"
CODEX_BEGIN = "# BEGIN TRUTHDECK OWNED v1"
CODEX_END = "# END TRUTHDECK OWNED v1"


class InstallError(RuntimeError):
    pass


def install(*, repo_root: Path, home: Path, enable_mcp: str = "none", path_value: str | None = None) -> dict[str, Any]:
    repo_root, home = repo_root.resolve(strict=True), home.resolve()
    root = home / ".truthdeck"
    bin_dir, skill_dir = root / "bin", root / "skills" / "truthdeck"
    manifest_path = root / "install-manifest.json"
    if manifest_path.exists():
        current = status(home=home)
        if current["state"] != "installed":
            raise InstallError("existing TruthDeck install is not ownership-clean")
    bin_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    sources = sorted((repo_root / "scripts").glob("truthdeck*.py")) + [repo_root / "scripts" / "truthctl.py"]
    for source in sources:
        target = bin_dir / source.name
        _copy_atomic(source, target)
        files[str(target.relative_to(home))] = _sha(target)
    _copy_atomic(repo_root / "skills" / "truthdeck" / "SKILL.md", skill_dir / "SKILL.md")
    files[str((skill_dir / "SKILL.md").relative_to(home))] = _sha(skill_dir / "SKILL.md")
    registry = root / "registry.json"
    template = repo_root / "templates" / "truthdeck.registry.json.template"
    if not registry.exists():
        _copy_atomic(template, registry)
    elif registry.read_bytes() != template.read_bytes():
        _copy_atomic(template, root / "registry.json.from-template")
        files[str((root / "registry.json.from-template").relative_to(home))] = _sha(root / "registry.json.from-template")
    shim = _install_shim(home, bin_dir / "truthctl.py", path_value or os.environ.get("PATH", ""))
    if shim:
        files[str(shim.relative_to(home))] = _sha(shim)
    config_backups: list[str] = []
    if enable_mcp in {"codex", "both"}:
        backup = _register_codex(home, bin_dir / "truthdeck_mcp.py")
        if backup:
            config_backups.append(str(backup.relative_to(home)))
    if enable_mcp in {"claude", "both"}:
        backup = _register_claude(home, bin_dir / "truthdeck_mcp.py")
        if backup:
            config_backups.append(str(backup.relative_to(home)))
    manifest = {
        "schema_version": MANIFEST_SCHEMA, "files": files, "mcp": enable_mcp,
        "config_backups": config_backups,
        "canonical_command": [sys.executable, str(bin_dir / "truthctl.py")],
        "shim": str(shim) if shim else None,
    }
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    return {"state": "installed", "manifest": str(manifest_path), "shim": str(shim) if shim else None,
            "path_state": "PASS" if shim else "HOLD", "canonical_command": manifest["canonical_command"], "mcp": enable_mcp}


def status(*, home: Path) -> dict[str, Any]:
    manifest_path = home.resolve() / ".truthdeck" / "install-manifest.json"
    if not manifest_path.exists():
        return {"state": "absent"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "invalid_manifest"}
    drift = []
    for relative, digest in manifest.get("files", {}).items():
        target = home / relative
        if not target.exists() or _sha(target) != digest:
            drift.append(relative)
    return {"state": "installed" if not drift else "drifted", "drift": drift,
            "mcp": manifest.get("mcp", "none"), "shim": manifest.get("shim")}


def uninstall(*, home: Path) -> dict[str, Any]:
    home = home.resolve()
    root, manifest_path = home / ".truthdeck", home / ".truthdeck" / "install-manifest.json"
    if not manifest_path.exists():
        return {"state": "absent"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = status(home=home)
    if current["state"] != "installed":
        raise InstallError(f"refusing uninstall because owned files drifted: {current.get('drift')}")
    if manifest.get("mcp") in {"codex", "both"}:
        _remove_codex(home)
    if manifest.get("mcp") in {"claude", "both"}:
        _remove_claude(home)
    for relative in manifest.get("files", {}):
        (home / relative).unlink(missing_ok=True)
    manifest_path.unlink()
    for directory in (root / "skills" / "truthdeck", root / "skills", root / "bin"):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"state": "uninstalled", "snapshots_preserved": (root / "snapshots").exists(), "registry_preserved": (root / "registry.json").exists()}


def _install_shim(home: Path, cli: Path, path_value: str) -> Path | None:
    for raw in path_value.split(os.pathsep):
        if not raw:
            continue
        directory = Path(raw).resolve()
        if directory.exists() and (directory == home or home in directory.parents):
            target = directory / "truthctl.cmd"
            payload = f'@echo off\r\n"{sys.executable}" "{cli}" %*\r\n'.encode()
            _write_atomic(target, payload)
            return target
    return None


def _register_codex(home: Path, server: Path) -> Path | None:
    path = home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if CODEX_BEGIN in original:
        block = original[original.index(CODEX_BEGIN):original.index(CODEX_END) + len(CODEX_END)]
        if str(server) not in block:
            raise InstallError("foreign or stale TruthDeck Codex MCP block")
        return None
    backup = _backup(path) if path.exists() else None
    block = f'{CODEX_BEGIN}\n[mcp_servers.truthdeck]\ncommand = {json.dumps(sys.executable)}\nargs = [{json.dumps(str(server))}]\n{CODEX_END}\n'
    candidate = original.rstrip() + ("\n\n" if original.strip() else "") + block
    tomllib.loads(candidate)
    _write_atomic(path, candidate.encode())
    tomllib.loads(path.read_text(encoding="utf-8"))
    return backup


def _remove_codex(home: Path) -> None:
    path = home / ".codex" / "config.toml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if CODEX_BEGIN not in text:
        return
    before, rest = text.split(CODEX_BEGIN, 1)
    _, after = rest.split(CODEX_END, 1)
    candidate = (before.rstrip() + "\n" + after.lstrip("\n")).lstrip("\n")
    tomllib.loads(candidate or "")
    _write_atomic(path, candidate.encode())


def _register_claude(home: Path, server: Path) -> Path | None:
    path = home / ".claude.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    servers = raw.setdefault("mcpServers", {})
    if "truthdeck" in servers:
        if servers["truthdeck"].get("_truthdeck_owner") != MANIFEST_SCHEMA:
            raise InstallError("foreign Claude MCP entry named truthdeck")
        return None
    backup = _backup(path) if path.exists() else None
    servers["truthdeck"] = {"type": "stdio", "command": sys.executable, "args": [str(server)], "_truthdeck_owner": MANIFEST_SCHEMA}
    _write_atomic(path, json.dumps(raw, indent=2, sort_keys=True).encode() + b"\n")
    json.loads(path.read_text(encoding="utf-8"))
    return backup


def _remove_claude(home: Path) -> None:
    path = home / ".claude.json"
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    entry = raw.get("mcpServers", {}).get("truthdeck")
    if entry and entry.get("_truthdeck_owner") == MANIFEST_SCHEMA:
        del raw["mcpServers"]["truthdeck"]
        _write_atomic(path, json.dumps(raw, indent=2, sort_keys=True).encode() + b"\n")


def _backup(path: Path) -> Path:
    digest = _sha(path)[:12]
    target = path.with_name(f"{path.name}.truthdeck-backup-{digest}")
    if not target.exists():
        shutil.copy2(path, target)
    return target


def _copy_atomic(source: Path, target: Path) -> None:
    _write_atomic(target, source.read_bytes())


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="truthdeck-install")
    parser.add_argument("command", choices=("install", "status", "uninstall"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--enable-mcp", choices=("none", "claude", "codex", "both"), default="none")
    args = parser.parse_args(argv)
    try:
        result = install(repo_root=args.repo_root, home=args.home, enable_mcp=args.enable_mcp) if args.command == "install" else status(home=args.home) if args.command == "status" else uninstall(home=args.home)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["state"] not in {"drifted", "invalid_manifest"} else 11
    except (InstallError, OSError, ValueError) as exc:
        print(json.dumps({"state": "HOLD", "error": str(exc)[:500]}), file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
