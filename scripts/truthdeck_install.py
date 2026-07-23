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
MAX_MANIFEST_BYTES = 1_048_576
CODEX_BEGIN = "# BEGIN TRUTHDECK OWNED v1"
CODEX_END = "# END TRUTHDECK OWNED v1"


class InstallError(RuntimeError):
    pass


def install(*, repo_root: Path, home: Path, enable_mcp: str = "none", path_value: str | None = None) -> dict[str, Any]:
    repo_root, home = repo_root.resolve(strict=True), home.resolve()
    root = home / ".truthdeck"
    bin_dir, skill_dir = root / "bin", root / "skills" / "truthdeck"
    manifest_path = root / "install-manifest.json"
    existing_manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        current = status(home=home)
        if current["state"] != "installed":
            raise InstallError("existing TruthDeck install is not ownership-clean")
        existing_manifest = _load_manifest(manifest_path, home)
    sources = sorted((repo_root / "scripts").glob("truthdeck*.py")) + [repo_root / "scripts" / "truthctl.py"]
    effective_path = path_value if path_value is not None else os.environ.get("PATH", "")
    shim_target = _shim_candidate(home, effective_path)
    targets = [bin_dir / source.name for source in sources]
    discovery_skills = (home / ".codex" / "skills" / "truthdeck" / "SKILL.md",
                        home / ".claude" / "skills" / "truthdeck" / "SKILL.md")
    targets.extend((skill_dir / "SKILL.md", *discovery_skills, root / "registry.json",
                    root / "registry.json.from-template", manifest_path))
    if shim_target:
        targets.append(shim_target)
    previous_mcp = str((existing_manifest or {}).get("mcp", "none"))
    config_targets = set(_selected_configs(home, enable_mcp)) | set(_selected_configs(home, previous_mcp))
    for config in config_targets:
        targets.append(config)
        if config.exists():
            targets.append(config.with_name(f"{config.name}.truthdeck-backup-{_sha(config)[:12]}"))
    before = {target: target.read_bytes() if target.exists() else None for target in targets}
    owned = set((existing_manifest or {}).get("files", {}))
    try:
        return _install_mutations(repo_root=repo_root, home=home, enable_mcp=enable_mcp,
                                  previous_mcp=previous_mcp, sources=sources,
                                  effective_path=effective_path, owned=owned)
    except Exception:
        _rollback(before)
        for directory in (skill_dir, root / "skills", bin_dir, root,
                          home / ".codex" / "skills" / "truthdeck",
                          home / ".claude" / "skills" / "truthdeck", home / ".codex"):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _install_mutations(*, repo_root: Path, home: Path, enable_mcp: str, previous_mcp: str,
                       sources: list[Path], effective_path: str, owned: set[str]) -> dict[str, Any]:
    root = home / ".truthdeck"
    bin_dir, skill_dir = root / "bin", root / "skills" / "truthdeck"
    manifest_path = root / "install-manifest.json"
    bin_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for source in sources:
        target = bin_dir / source.name
        _copy_atomic(source, target)
        files[str(target.relative_to(home))] = _sha(target)
    _copy_atomic(repo_root / "skills" / "truthdeck" / "SKILL.md", skill_dir / "SKILL.md")
    files[str((skill_dir / "SKILL.md").relative_to(home))] = _sha(skill_dir / "SKILL.md")
    for target in (home / ".codex" / "skills" / "truthdeck" / "SKILL.md",
                   home / ".claude" / "skills" / "truthdeck" / "SKILL.md"):
        relative = str(target.relative_to(home))
        if target.exists() and relative not in owned:
            raise InstallError(f"refusing to overwrite foreign skill: {target}")
        _copy_atomic(repo_root / "skills" / "truthdeck" / "SKILL.md", target)
        files[relative] = _sha(target)
    registry = root / "registry.json"
    template = repo_root / "templates" / "truthdeck.registry.json.template"
    if not registry.exists():
        _copy_atomic(template, registry)
    elif registry.read_bytes() != template.read_bytes():
        _copy_atomic(template, root / "registry.json.from-template")
        files[str((root / "registry.json.from-template").relative_to(home))] = _sha(root / "registry.json.from-template")
    shim = _install_shim(home, bin_dir / "truthctl.py", effective_path, owned)
    if shim:
        files[str(shim.relative_to(home))] = _sha(shim)
    config_backups: list[str] = []
    if previous_mcp in {"codex", "both"} and enable_mcp not in {"codex", "both"}:
        _remove_codex(home)
    if previous_mcp in {"claude", "both"} and enable_mcp not in {"claude", "both"}:
        _remove_claude(home)
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
    home = home.resolve()
    manifest_path = home / ".truthdeck" / "install-manifest.json"
    if not manifest_path.exists():
        return {
            "state": "absent", "cli_installed": False,
            "codex_skill_installed": False, "claude_skill_installed": False,
            "mcp_codex_active": False, "mcp_claude_active": False,
        }
    try:
        manifest = _load_manifest(manifest_path, home)
    except (OSError, ValueError, InstallError):
        return {"state": "invalid_manifest"}
    drift = []
    for relative, digest in manifest.get("files", {}).items():
        target = _owned_target(home, relative)
        if not target.exists() or _sha(target) != digest:
            drift.append(relative)
    state = "installed" if not drift else "drifted"
    owned = set(manifest["files"])
    return {
        "state": state, "drift": drift, "mcp": manifest.get("mcp", "none"),
        "shim": manifest.get("shim"),
        "cli_installed": state == "installed" and str(Path(".truthdeck/bin/truthctl.py")) in owned,
        "codex_skill_installed": state == "installed" and str(Path(".codex/skills/truthdeck/SKILL.md")) in owned,
        "claude_skill_installed": state == "installed" and str(Path(".claude/skills/truthdeck/SKILL.md")) in owned,
        "mcp_codex_active": _codex_active(home, manifest),
        "mcp_claude_active": _claude_active(home, manifest),
    }


def uninstall(*, home: Path) -> dict[str, Any]:
    home = home.resolve()
    root, manifest_path = home / ".truthdeck", home / ".truthdeck" / "install-manifest.json"
    if not manifest_path.exists():
        return {"state": "absent"}
    manifest = _load_manifest(manifest_path, home)
    current = status(home=home)
    if current["state"] != "installed":
        raise InstallError(f"refusing uninstall because owned files drifted: {current.get('drift')}")
    targets = [_owned_target(home, relative) for relative in manifest["files"]]
    if manifest.get("mcp") in {"codex", "both"}:
        _remove_codex(home)
    if manifest.get("mcp") in {"claude", "both"}:
        _remove_claude(home)
    for target in targets:
        target.unlink(missing_ok=True)
    manifest_path.unlink()
    for directory in (root / "skills" / "truthdeck", root / "skills", root / "bin",
                      home / ".codex" / "skills" / "truthdeck",
                      home / ".claude" / "skills" / "truthdeck"):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"state": "uninstalled", "snapshots_preserved": (root / "snapshots").exists(), "registry_preserved": (root / "registry.json").exists()}


def _install_shim(home: Path, cli: Path, path_value: str, owned: set[str]) -> Path | None:
    target = _shim_candidate(home, path_value)
    if target is None:
        return None
    relative = str(target.relative_to(home))
    if target.exists() and relative not in owned:
        raise InstallError(f"refusing to overwrite foreign shim: {target}")
    _, payload = _shim_spec(sys.executable, cli, os.name)
    _write_atomic(target, payload)
    if os.name != "nt":
        target.chmod(0o755)
    return target


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
    if not isinstance(servers, dict):
        raise InstallError("Claude mcpServers must be an object")
    if "truthdeck" in servers:
        if not isinstance(servers["truthdeck"], dict) or servers["truthdeck"].get("_truthdeck_owner") != MANIFEST_SCHEMA:
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


def _shim_candidate(home: Path, path_value: str) -> Path | None:
    name, _ = _shim_spec(sys.executable, Path("truthctl.py"), os.name)
    for raw in path_value.split(os.pathsep):
        if not raw:
            continue
        directory = Path(raw).resolve()
        if directory.exists() and (directory == home or home in directory.parents):
            return directory / name
    return None


def _selected_configs(home: Path, enable_mcp: str) -> tuple[Path, ...]:
    paths = []
    if enable_mcp in {"codex", "both"}:
        paths.append(home / ".codex" / "config.toml")
    if enable_mcp in {"claude", "both"}:
        paths.append(home / ".claude.json")
    return tuple(paths)


def _shim_spec(python: str, cli: Path, platform: str) -> tuple[str, bytes]:
    if platform == "nt":
        return "truthctl.cmd", f'@echo off\r\n"{python}" "{cli}" %*\r\n'.encode()
    return "truthctl", f'#!/bin/sh\nexec "{python}" "{cli}" "$@"\n'.encode()


def _rollback(before: dict[Path, bytes | None]) -> None:
    for path, payload in reversed(tuple(before.items())):
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _write_atomic(path, payload)


def _load_manifest(path: Path, home: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise InstallError("install manifest exceeds size limit")
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = {"schema_version", "files", "mcp", "config_backups", "canonical_command", "shim"}
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema_version") != MANIFEST_SCHEMA:
        raise InstallError("invalid install manifest schema")
    if raw.get("mcp") not in {"none", "codex", "claude", "both"} or not isinstance(raw.get("files"), dict):
        raise InstallError("invalid install manifest values")
    for relative, digest in raw["files"].items():
        _owned_target(home, relative)
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise InstallError("invalid owned file digest")
    return raw


def _codex_active(home: Path, manifest: dict[str, Any]) -> bool:
    if manifest.get("mcp") not in {"codex", "both"}:
        return False
    path = home / ".codex" / "config.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        entry = raw.get("mcp_servers", {}).get("truthdeck", {})
        expected = str(home / ".truthdeck" / "bin" / "truthdeck_mcp.py")
        return isinstance(entry, dict) and entry.get("args") == [expected]
    except (OSError, ValueError, AttributeError):
        return False


def _claude_active(home: Path, manifest: dict[str, Any]) -> bool:
    if manifest.get("mcp") not in {"claude", "both"}:
        return False
    path = home / ".claude.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entry = raw.get("mcpServers", {}).get("truthdeck", {})
        expected = str(home / ".truthdeck" / "bin" / "truthdeck_mcp.py")
        return (isinstance(entry, dict) and entry.get("_truthdeck_owner") == MANIFEST_SCHEMA
                and entry.get("args") == [expected])
    except (OSError, ValueError, AttributeError):
        return False


def _owned_target(home: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise InstallError("owned path must be relative")
    target = (home / relative).resolve()
    if target == home or home not in target.parents:
        raise InstallError(f"owned path escapes home: {relative}")
    return target


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
