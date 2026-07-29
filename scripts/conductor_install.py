"""Ownership-checked installer and read-only status for TruthDeck Conductor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_store import read_store_diagnostics  # noqa: E402

MANIFEST_SCHEMA = "conductor.install.v1"
MAX_MANIFEST_BYTES = 1_048_576
TOOL_SCRIPTS = {
    "conductorctl": "conductorctl.py",
    "conductord": "conductord.py",
    "conductor_mcp": "conductor_mcp.py",
    "conductor_install": "conductor_install.py",
}


class InstallError(RuntimeError):
    """Installer refused an unsafe or ownership-ambiguous mutation."""


def compute_file_hash(filepath: pathlib.Path) -> str:
    """Compute a SHA-256 digest."""
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


def install(
    root_dir: Optional[pathlib.Path] = None,
    *,
    repo_root: Optional[pathlib.Path] = None,
    home: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Install an isolated owned runtime without starting or registering a daemon."""
    root, ownership_home = _resolve_locations(root_dir=root_dir, home=home)
    source_root = (repo_root or pathlib.Path(__file__).resolve().parent.parent).resolve(strict=True)
    manifest_path = root / "install-manifest.json"
    existing_manifest: Dict[str, Any] | None = None
    if manifest_path.exists():
        current = check_status(root_dir=root, repo_root=source_root)
        if current["state"] not in {"INSTALLED", "SOURCE_MISMATCH"}:
            raise InstallError("existing Conductor install is not ownership-clean")
        existing_manifest = _load_manifest(manifest_path, ownership_home)
        if read_store_diagnostics(root).get("leader_active"):
            raise InstallError("refusing upgrade while an active Conductor leader owns the store")

    script_sources = sorted((source_root / "scripts").glob("conductor*.py"))
    if not script_sources or not all((source_root / "scripts" / name).is_file() for name in TOOL_SCRIPTS.values()):
        raise InstallError("source repository does not contain the complete Conductor runtime")
    skill_source = source_root / "skills" / "conductor" / "SKILL.md"
    if not skill_source.is_file():
        raise InstallError("source repository does not contain skills/conductor/SKILL.md")

    app_scripts = root / "app" / "scripts"
    local_skill = root / "skills" / "conductor" / "SKILL.md"
    discovery_skills = (
        ownership_home / ".codex" / "skills" / "conductor" / "SKILL.md",
        ownership_home / ".claude" / "skills" / "conductor" / "SKILL.md",
    )
    payloads: Dict[pathlib.Path, bytes] = {
        app_scripts / source.name: source.read_bytes() for source in script_sources
    }
    payloads[app_scripts / "__init__.py"] = b'"""Installed TruthDeck Conductor runtime package."""\n'
    payloads[local_skill] = skill_source.read_bytes()
    for target in discovery_skills:
        payloads[target] = skill_source.read_bytes()

    canonical_commands: Dict[str, list[str]] = {}
    shims: Dict[str, list[str]] = {}
    for tool_name, script_name in TOOL_SCRIPTS.items():
        installed_script = app_scripts / script_name
        canonical_commands[tool_name] = [sys.executable, str(installed_script)]
        cmd_target = root / "bin" / f"{tool_name}.cmd"
        posix_target = root / "bin" / tool_name
        payloads[cmd_target] = _shim_payload(sys.executable, installed_script, "nt")
        payloads[posix_target] = _shim_payload(sys.executable, installed_script, "posix")
        shims[tool_name] = [str(cmd_target), str(posix_target)]

    existing_files = dict((existing_manifest or {}).get("files", {}))
    for target in payloads:
        relative = _relative_owned_path(ownership_home, target)
        if target.exists() and relative not in existing_files:
            raise InstallError(f"refusing to overwrite foreign file: {target}")

    stale_targets = [
        _owned_target(ownership_home, relative)
        for relative in existing_files
        if _owned_target(ownership_home, relative) not in payloads
    ]
    backup_payloads: Dict[pathlib.Path, bytes] = {}
    for target, payload in payloads.items():
        if target.exists() and target.read_bytes() != payload:
            digest = compute_file_hash(target)
            backup = root / "backups" / "installer" / f"{_safe_backup_name(target, ownership_home)}.{digest[:12]}.bak"
            if not backup.exists():
                backup_payloads[backup] = target.read_bytes()

    all_targets = set(payloads) | set(stale_targets) | set(backup_payloads) | {manifest_path}
    before = {target: target.read_bytes() if target.exists() else None for target in all_targets}
    try:
        for backup, payload in backup_payloads.items():
            _write_atomic(backup, payload)
        files: Dict[str, str] = {}
        for target, payload in payloads.items():
            _write_atomic(target, payload)
            if target.suffix == "" and target.parent == root / "bin" and os.name != "nt":
                target.chmod(0o755)
            files[_relative_owned_path(ownership_home, target)] = compute_file_hash(target)
        for stale in stale_targets:
            relative = _relative_owned_path(ownership_home, stale)
            expected = existing_files[relative]
            if stale.exists() and compute_file_hash(stale) != expected:
                raise InstallError(f"refusing to remove drifted owned file: {stale}")
            stale.unlink(missing_ok=True)

        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "files": files,
            "source_head_sha": _source_head(source_root),
            "source_tree_sha256": _source_tree_hash(script_sources + [skill_source]),
            "interpreter": sys.executable,
            "canonical_commands": canonical_commands,
            "shims": shims,
        }
        _write_atomic(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n")
    except Exception:
        _rollback(before)
        _remove_empty_owned_directories(root, ownership_home)
        raise
    return check_status(root_dir=root, repo_root=source_root)


def check_status(
    root_dir: Optional[pathlib.Path] = None,
    *,
    repo_root: Optional[pathlib.Path] = None,
    home: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Read installation and store state without creating or changing any file."""
    root, ownership_home = _resolve_locations(root_dir=root_dir, home=home)
    manifest_path = root / "install-manifest.json"
    store = read_store_diagnostics(root)
    if not manifest_path.is_file():
        return {
            "state": "ABSENT",
            "root_dir": str(root),
            "manifest": str(manifest_path),
            "db_exists": store["db_exists"],
            "leader_active": store.get("leader_active", False),
        }
    try:
        manifest = _load_manifest(manifest_path, ownership_home)
    except (InstallError, OSError, ValueError, json.JSONDecodeError):
        return {
            "state": "INVALID_MANIFEST",
            "root_dir": str(root),
            "manifest": str(manifest_path),
            "db_exists": store["db_exists"],
            "leader_active": store.get("leader_active", False),
        }

    drift = []
    for relative, digest in manifest["files"].items():
        target = _owned_target(ownership_home, relative)
        if not target.is_file() or compute_file_hash(target) != digest:
            drift.append(relative)
    state = "INSTALLED" if not drift else "DRIFTED"
    current_source_head = None
    current_source_tree = None
    if repo_root is not None:
        try:
            resolved_source = repo_root.resolve(strict=True)
            current_source_head = _source_head(resolved_source)
            current_sources = sorted((resolved_source / "scripts").glob("conductor*.py"))
            current_sources.append(resolved_source / "skills" / "conductor" / "SKILL.md")
            if not current_sources or not all(source.is_file() for source in current_sources):
                raise OSError("incomplete Conductor source tree")
            current_source_tree = _source_tree_hash(current_sources)
        except (OSError, subprocess.SubprocessError):
            current_source_head = "UNKNOWN"
            current_source_tree = "UNKNOWN"
        if state == "INSTALLED" and (
            current_source_head != manifest["source_head_sha"]
            or current_source_tree != manifest["source_tree_sha256"]
        ):
            state = "SOURCE_MISMATCH"
    return {
        "state": state,
        "root_dir": str(root),
        "manifest": str(manifest_path),
        "drift": sorted(drift),
        "installed_source_head": manifest["source_head_sha"],
        "current_source_head": current_source_head,
        "source_tree_sha256": manifest["source_tree_sha256"],
        "current_source_tree_sha256": current_source_tree,
        "interpreter": manifest["interpreter"],
        "canonical_commands": manifest["canonical_commands"],
        "shims": manifest["shims"],
        "db_exists": store["db_exists"],
        "leader_active": store.get("leader_active", False),
    }


def uninstall(
    root_dir: Optional[pathlib.Path] = None,
    *,
    home: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Remove only ownership-clean installed files and preserve all runtime state."""
    root, ownership_home = _resolve_locations(root_dir=root_dir, home=home)
    manifest_path = root / "install-manifest.json"
    if not manifest_path.is_file():
        return {"state": "ABSENT", "root_dir": str(root)}
    manifest = _load_manifest(manifest_path, ownership_home)
    current = check_status(root_dir=root)
    if current["state"] != "INSTALLED":
        raise InstallError(f"refusing uninstall because owned files are not clean: {current.get('drift')}")
    if current.get("leader_active"):
        raise InstallError("refusing uninstall while an active Conductor leader owns the store")
    for relative, digest in manifest["files"].items():
        target = _owned_target(ownership_home, relative)
        if not target.is_file() or compute_file_hash(target) != digest:
            raise InstallError(f"refusing to remove drifted owned file: {target}")
    for relative in manifest["files"]:
        _owned_target(ownership_home, relative).unlink()
    manifest_path.unlink()
    _remove_empty_owned_directories(root, ownership_home)
    return {
        "state": "UNINSTALLED",
        "root_dir": str(root),
        "db_preserved": (root / "conductor.db").exists(),
        "receipts_preserved": (root / "receipts").exists(),
        "artifacts_preserved": (root / "artifacts").exists(),
        "backups_preserved": (root / "backups").exists(),
    }


def _resolve_locations(
    *,
    root_dir: Optional[pathlib.Path],
    home: Optional[pathlib.Path],
) -> tuple[pathlib.Path, pathlib.Path]:
    if root_dir is not None and home is not None:
        raise ValueError("pass root_dir or home, not both")
    if root_dir is not None:
        root = pathlib.Path(root_dir).expanduser().resolve()
        return root, root.parent
    ownership_home = pathlib.Path(home or pathlib.Path.home()).expanduser().resolve()
    return ownership_home / ".conductor", ownership_home


def _load_manifest(path: pathlib.Path, ownership_home: pathlib.Path) -> Dict[str, Any]:
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise InstallError("install manifest exceeds size limit")
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "files",
        "source_head_sha",
        "source_tree_sha256",
        "interpreter",
        "canonical_commands",
        "shims",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw.get("schema_version") != MANIFEST_SCHEMA:
        raise InstallError("invalid install manifest schema")
    if not isinstance(raw["files"], dict) or not isinstance(raw["canonical_commands"], dict):
        raise InstallError("invalid install manifest values")
    if (
        not _is_hex_digest(raw["source_head_sha"], lengths={40, 64})
        or not _is_hex_digest(raw["source_tree_sha256"], lengths={64})
        or not isinstance(raw["interpreter"], str)
        or set(raw["canonical_commands"]) != set(TOOL_SCRIPTS)
        or set(raw["shims"]) != set(TOOL_SCRIPTS)
    ):
        raise InstallError("invalid install manifest identity")
    seen_targets = set()
    for relative, digest in raw["files"].items():
        target = _owned_target(ownership_home, relative)
        normalized = os.path.normcase(str(target))
        if normalized in seen_targets:
            raise InstallError("install manifest aliases one owned target more than once")
        seen_targets.add(normalized)
        if not _is_hex_digest(digest, lengths={64}):
            raise InstallError("invalid owned file digest")
    for command in raw["canonical_commands"].values():
        if not isinstance(command, list) or len(command) != 2 or not all(isinstance(value, str) for value in command):
            raise InstallError("invalid canonical command")
    for shim_pair in raw["shims"].values():
        if not isinstance(shim_pair, list) or len(shim_pair) != 2 or not all(isinstance(value, str) for value in shim_pair):
            raise InstallError("invalid shim manifest value")
    return raw


def _owned_target(ownership_home: pathlib.Path, relative: str) -> pathlib.Path:
    if not isinstance(relative, str) or pathlib.Path(relative).is_absolute():
        raise InstallError("owned path must be relative")
    relative_path = pathlib.Path(relative)
    if ".." in relative_path.parts:
        raise InstallError(f"owned path escapes installation home: {relative}")
    target = pathlib.Path(os.path.abspath(ownership_home / relative_path))
    _assert_no_link_chain(ownership_home, target)
    if target == ownership_home or ownership_home not in target.parents:
        raise InstallError(f"owned path escapes installation home: {relative}")
    return target


def _relative_owned_path(ownership_home: pathlib.Path, target: pathlib.Path) -> str:
    absolute = pathlib.Path(os.path.abspath(target))
    _assert_no_link_chain(ownership_home, absolute)
    if absolute == ownership_home or ownership_home not in absolute.parents:
        raise InstallError(f"owned target escapes installation home: {target}")
    return str(absolute.relative_to(ownership_home))


def _assert_no_link_chain(ownership_home: pathlib.Path, target: pathlib.Path) -> None:
    try:
        relative = target.relative_to(ownership_home)
    except ValueError as exc:
        raise InstallError(f"owned target escapes installation home: {target}") from exc
    cursor = ownership_home
    for part in relative.parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", lambda: False)
        if cursor.is_symlink() or is_junction():
            raise InstallError(f"owned path crosses a symlink or junction: {cursor}")


def _is_hex_digest(value: Any, *, lengths: set[int]) -> bool:
    return (
        isinstance(value, str)
        and len(value) in lengths
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_atomic(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        pathlib.Path(name).unlink(missing_ok=True)


def _rollback(before: Dict[pathlib.Path, bytes | None]) -> None:
    for path, payload in reversed(tuple(before.items())):
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            _write_atomic(path, payload)


def _remove_empty_owned_directories(root: pathlib.Path, ownership_home: pathlib.Path) -> None:
    candidates = [
        ownership_home / ".codex" / "skills" / "conductor",
        ownership_home / ".claude" / "skills" / "conductor",
        root / "skills" / "conductor",
        root / "skills",
        root / "app" / "scripts",
        root / "app",
        root / "bin",
        root,
    ]
    for directory in candidates:
        try:
            directory.rmdir()
        except OSError:
            pass


def _safe_backup_name(target: pathlib.Path, ownership_home: pathlib.Path) -> str:
    return str(target.resolve().relative_to(ownership_home)).replace("\\", "__").replace("/", "__")


def _shim_payload(python: str, script: pathlib.Path, platform: str) -> bytes:
    if platform == "nt":
        return f'@echo off\r\n"{python}" "{script}" %*\r\n'.encode()
    return f'#!/bin/sh\nexec "{python}" "{script}" "$@"\n'.encode()


def _source_head(repo_root: pathlib.Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _source_tree_hash(sources: list[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for source in sorted(sources):
        digest.update(source.name.encode())
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor-install")
    parser.add_argument("command", choices=("install", "status", "uninstall"))
    parser.add_argument("--repo-root", type=pathlib.Path)
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            source_root = args.repo_root or pathlib.Path(__file__).resolve().parents[1]
            result = install(repo_root=source_root, home=args.home)
        elif args.command == "status":
            source_candidate = pathlib.Path(__file__).resolve().parents[1]
            status_source = args.repo_root or (source_candidate if (source_candidate / ".git").exists() else None)
            result = check_status(home=args.home, repo_root=status_source)
        else:
            result = uninstall(home=args.home)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["state"] not in {"DRIFTED", "INVALID_MANIFEST", "SOURCE_MISMATCH"} else 11
    except (InstallError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"state": "HOLD", "error": str(exc)[:500]}), file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
