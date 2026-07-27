#!/usr/bin/env python3
"""Install the global Codex lifecycle hook and shared repository registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from session_state import atomic_write_bytes, resolve_repository


@dataclass(frozen=True)
class InstallResult:
    changed: bool
    manifest_path: Path | None


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _encoded(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_target(path: Path, previous: bytes | None) -> None:
    current = _read_optional(path)
    if current == previous:
        return
    if previous is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    atomic_write_bytes(path, previous)


def _assert_unchanged(path: Path, expected: bytes | None, *, label: str) -> None:
    if _read_optional(path) != expected:
        raise RuntimeError(f"target changed during operation: {label}")


def _restore_if_installed(
    path: Path,
    *,
    installed: bytes,
    previous: bytes | None,
) -> bool:
    if _read_optional(path) != installed:
        return False
    _restore_target(path, previous)
    return True


def _windows_command(*arguments: str | Path) -> str:
    values = tuple(str(argument) for argument in arguments)
    if any(any(character in value for character in '"\r\n%!') for value in values):
        raise ValueError("hook command path contains an unsafe cmd.exe character")
    return " ".join(f'"{value}"' for value in values)


def _render_hooks(template: dict[str, Any], command: str) -> dict[str, Any]:
    rendered = json.loads(json.dumps(template))
    hooks = rendered.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError("hook template is missing hooks")
    for groups in hooks.values():
        if not isinstance(groups, list):
            raise ValueError("hook event must contain matcher groups")
        for group in groups:
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                raise ValueError("hook matcher group is invalid")
            for handler in handlers:
                if not isinstance(handler, dict) or handler.get("type") != "command":
                    raise ValueError("only command hook handlers are supported")
                if handler.get("command") == "{{COMMAND}}":
                    handler["command"] = command
                if handler.get("commandWindows") == "{{COMMAND}}":
                    handler["commandWindows"] = command
    return rendered


def _handler_is_owned(
    handler: object,
    *,
    command: str,
    adapter_filename: str,
) -> bool:
    if not isinstance(handler, dict):
        return False
    adapter_pattern = re.compile(
        rf'(?i)(?:^|[\\/\s"]){re.escape(adapter_filename)}(?:"|\s|$)'
    )
    values = (handler.get("command"), handler.get("commandWindows"))
    return command in values or any(
        isinstance(value, str) and adapter_pattern.search(value)
        for value in values
    )


def _without_owned_handlers(
    group: object,
    *,
    command: str,
    adapter_filename: str,
) -> dict[str, Any] | None:
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        raise ValueError("existing hook matcher group is invalid")
    retained = [
        handler
        for handler in group["hooks"]
        if not _handler_is_owned(
            handler,
            command=command,
            adapter_filename=adapter_filename,
        )
    ]
    if not retained:
        return None
    result = dict(group)
    result["hooks"] = retained
    return result


def _merge_hooks(
    existing: dict[str, Any] | None,
    rendered: dict[str, Any],
    *,
    command: str,
    adapter_filename: str,
) -> dict[str, Any]:
    if existing is None:
        return rendered
    merged = json.loads(json.dumps(existing))
    existing_hooks = merged.get("hooks")
    rendered_hooks = rendered.get("hooks")
    if not isinstance(existing_hooks, dict) or not isinstance(rendered_hooks, dict):
        raise ValueError("existing hooks file is invalid")
    for event, owned_groups in rendered_hooks.items():
        current_groups = existing_hooks.get(event, [])
        if not isinstance(current_groups, list) or not isinstance(owned_groups, list):
            raise ValueError("hook event must contain matcher groups")
        retained_groups = [
            retained
            for group in current_groups
            if (
                retained := _without_owned_handlers(
                    group,
                    command=command,
                    adapter_filename=adapter_filename,
                )
            )
            is not None
        ]
        existing_hooks[event] = [
            *retained_groups,
            *owned_groups,
        ]
    return merged


def _validate_registry(path: Path, payload: dict[str, Any], *, state_dir: Path) -> None:
    repositories = payload.get("repositories")
    if (
        payload.get("schema_version") != "session.registry.v1"
        or not isinstance(repositories, list)
    ):
        raise ValueError("registry template schema mismatch")
    seen_roots: set[str] = set()
    for entry in repositories:
        if not isinstance(entry, dict) or not isinstance(entry.get("root"), str):
            raise ValueError("registry entry is invalid")
        root = Path(entry["root"])
        root_key = _registry_key(entry)
        if root_key in seen_roots:
            raise ValueError(f"duplicate registry root: {root}")
        seen_roots.add(root_key)
        resolved = resolve_repository(
            root,
            registry_path=path,
            state_dir=state_dir,
            git_timeout_s=5.0,
        )
        if resolved is None or resolved.canonical_root != root.resolve(strict=False):
            raise ValueError(f"registry root is not a matching Git repository: {root}")
        configured_paths = (
            *((candidate, "directory") for candidate in resolved.plan_paths),
            *((candidate, "directory") for candidate in resolved.vision_paths),
            *((candidate, "file") for candidate in resolved.idea_paths),
        )
        for relative, expected_kind in configured_paths:
            candidate = root / relative
            valid = candidate.is_dir() if expected_kind == "directory" else candidate.is_file()
            if not valid:
                raise ValueError(
                    f"registry {expected_kind} path does not exist: {candidate}"
                )


def _registry_key(entry: dict[str, Any]) -> str:
    raw_root = entry.get("root")
    if not isinstance(raw_root, str):
        raise ValueError("registry entry root is invalid")
    root = Path(raw_root).expanduser()
    if not root.is_absolute():
        raise ValueError("registry entry root must be absolute")
    return os.path.normcase(os.path.normpath(str(root.resolve(strict=False))))


def _merge_registry(
    existing: dict[str, Any] | None,
    template: dict[str, Any],
) -> dict[str, Any]:
    if existing is None:
        return template
    if (
        existing.get("schema_version") != "session.registry.v1"
        or not isinstance(existing.get("repositories"), list)
        or not isinstance(template.get("repositories"), list)
    ):
        raise ValueError("existing registry schema mismatch")
    if not all(isinstance(entry, dict) for entry in existing["repositories"]):
        raise ValueError("existing registry contains an invalid entry")
    template_entries = template["repositories"]
    replacement_keys = {
        _registry_key(entry)
        for entry in template_entries
        if isinstance(entry, dict)
    }
    unknown_entries = [
        entry
        for entry in existing["repositories"]
        if isinstance(entry, dict) and _registry_key(entry) not in replacement_keys
    ]
    return {
        "schema_version": "session.registry.v1",
        "repositories": [*template_entries, *unknown_entries],
    }


def install(
    *,
    hooks_path: Path,
    registry_path: Path,
    hooks_template_path: Path,
    registry_template_path: Path,
    adapter_path: Path,
    python_executable: Path,
    backup_root: Path,
    codex_version: str,
) -> InstallResult:
    """Install fresh rendered targets and record their provenance."""

    if not codex_version.startswith("codex-cli "):
        raise ValueError("unsupported Codex version output")
    adapter = adapter_path.resolve(strict=True)
    interpreter = python_executable.resolve(strict=True)
    command = _windows_command(interpreter, adapter)
    rendered_hooks = _render_hooks(_json(hooks_template_path), command)
    previous_hooks = _read_optional(hooks_path)
    previous_registry = _read_optional(registry_path)
    existing_hooks = None
    if previous_hooks is not None:
        existing_hooks = json.loads(previous_hooks)
        if not isinstance(existing_hooks, dict):
            raise ValueError("existing hooks file must contain a JSON object")
    hooks = _merge_hooks(
        existing_hooks,
        rendered_hooks,
        command=command,
        adapter_filename=adapter.name,
    )
    existing_registry = None
    if previous_registry is not None:
        existing_registry = json.loads(previous_registry)
        if not isinstance(existing_registry, dict):
            raise ValueError("existing registry must contain a JSON object")
    registry = _merge_registry(
        existing_registry,
        _json(registry_template_path),
    )
    validation_path = backup_root / ".registry-validation.json"
    atomic_write_bytes(validation_path, _encoded(registry))
    try:
        _validate_registry(
            validation_path,
            registry,
            state_dir=backup_root / "validation-state",
        )
    finally:
        try:
            validation_path.unlink()
        except FileNotFoundError:
            pass
    hooks_bytes = _encoded(hooks)
    registry_bytes = _encoded(registry)
    changed = previous_hooks != hooks_bytes or previous_registry != registry_bytes
    if not changed:
        return InstallResult(changed=False, manifest_path=None)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_dir = backup_root / f"codex-session-lifecycle-{stamp}"
    hooks_backup = manifest_dir / "hooks.before.json"
    registry_backup = manifest_dir / "registry.before.json"
    if previous_hooks is not None:
        atomic_write_bytes(hooks_backup, previous_hooks)
    if previous_registry is not None:
        atomic_write_bytes(registry_backup, previous_registry)

    try:
        _assert_unchanged(hooks_path, previous_hooks, label="hooks")
        atomic_write_bytes(hooks_path, hooks_bytes)
        _assert_unchanged(registry_path, previous_registry, label="registry")
        atomic_write_bytes(registry_path, registry_bytes)
        manifest = {
            "schema_version": "codex.session.lifecycle.install.v1",
            "codex_version": codex_version,
            "adapter_path": str(adapter),
            "python_executable": str(interpreter),
            "targets": {
                "hooks": {
                    "path": str(hooks_path.resolve(strict=False)),
                    "existed": previous_hooks is not None,
                    "backup_path": str(hooks_backup) if previous_hooks is not None else None,
                    "before_sha256": _sha256(previous_hooks),
                    "installed_sha256": _sha256(hooks_bytes),
                },
                "registry": {
                    "path": str(registry_path.resolve(strict=False)),
                    "existed": previous_registry is not None,
                    "backup_path": (
                        str(registry_backup) if previous_registry is not None else None
                    ),
                    "before_sha256": _sha256(previous_registry),
                    "installed_sha256": _sha256(registry_bytes),
                },
            },
            "rollback_command": _windows_command(
                interpreter,
                Path(__file__).resolve(),
                "--rollback",
                manifest_dir / "install_manifest.json",
            ),
        }
        manifest_path = manifest_dir / "install_manifest.json"
        atomic_write_bytes(manifest_path, _encoded(manifest))
    except BaseException:
        _restore_if_installed(
            registry_path,
            installed=registry_bytes,
            previous=previous_registry,
        )
        _restore_if_installed(
            hooks_path,
            installed=hooks_bytes,
            previous=previous_hooks,
        )
        raise
    return InstallResult(changed=changed, manifest_path=manifest_path)


def rollback(
    manifest_path: Path,
    *,
    allowed_backup_root: Path | None = None,
    expected_targets: dict[str, Path] | None = None,
) -> None:
    """Restore both targets only while they still match the installed hashes."""

    manifest_path = manifest_path.resolve(strict=True)
    if (
        allowed_backup_root is not None
        and manifest_path.parent.parent
        != allowed_backup_root.resolve(strict=False)
    ):
        raise ValueError("install manifest is outside the allowed backup root")
    manifest = _json(manifest_path)
    if manifest.get("schema_version") != "codex.session.lifecycle.install.v1":
        raise ValueError("install manifest schema mismatch")
    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("install manifest targets are missing")

    resolved: list[tuple[Path, bytes | None, bytes | None]] = []
    for name in ("hooks", "registry"):
        target = targets.get(name)
        if not isinstance(target, dict) or not isinstance(target.get("path"), str):
            raise ValueError(f"manifest target is invalid: {name}")
        path = Path(target["path"]).resolve(strict=False)
        if (
            expected_targets is not None
            and path != expected_targets[name].resolve(strict=False)
        ):
            raise ValueError(f"manifest target does not match configured path: {name}")
        current = _read_optional(path)
        if _sha256(current) != target.get("installed_sha256"):
            raise ValueError(f"installed target changed since activation: {name}")
        existed = target.get("existed")
        backup_raw = target.get("backup_path")
        if existed is True:
            if not isinstance(backup_raw, str):
                raise ValueError(f"manifest backup is missing: {name}")
            backup_path = Path(backup_raw).resolve(strict=True)
            if backup_path.parent != manifest_path.parent:
                raise ValueError(f"manifest backup is outside its install directory: {name}")
            previous = backup_path.read_bytes()
            if _sha256(previous) != target.get("before_sha256"):
                raise ValueError(f"manifest backup hash mismatch: {name}")
        elif existed is False:
            previous = None
        else:
            raise ValueError(f"manifest existence flag is invalid: {name}")
        resolved.append((path, previous, current))

    restored: list[tuple[Path, bytes | None]] = []
    try:
        for path, previous, installed in reversed(resolved):
            _assert_unchanged(path, installed, label=path.name)
            _restore_target(path, previous)
            restored.append((path, installed))
    except BaseException:
        for path, installed in reversed(restored):
            _restore_target(path, installed)
        raise


def _codex_executable(*, platform_name: str = os.name) -> str:
    candidate = "codex.cmd" if platform_name == "nt" else "codex"
    executable = shutil.which(candidate)
    if executable is None:
        raise RuntimeError(f"{candidate} is not on PATH")
    return executable


def _codex_version() -> str:
    result = subprocess.run(
        [_codex_executable(), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("codex --version failed")
    return result.stdout.strip()


def _codex_features() -> str:
    result = subprocess.run(
        [_codex_executable(), "features", "list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("codex features list failed")
    return result.stdout


def _require_stable_hooks(features: str) -> None:
    for line in features.splitlines():
        fields = line.split()
        if fields[:3] == ["hooks", "stable", "true"]:
            return
    raise RuntimeError("Codex does not report stable hooks support")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rollback",
        type=Path,
        help="restore targets recorded in an install manifest",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument(
        "--hooks-path",
        type=Path,
        default=Path.home() / ".codex" / "hooks.json",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=Path.home() / ".claude" / "session_registry.json",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path.home() / ".codex" / "backups",
    )
    args = parser.parse_args()
    if args.rollback is not None:
        rollback(
            args.rollback,
            allowed_backup_root=args.backup_root,
            expected_targets={
                "hooks": args.hooks_path,
                "registry": args.registry_path,
            },
        )
        print(
            json.dumps(
                {
                    "rolled_back": True,
                    "manifest_path": str(args.rollback),
                },
                separators=(",", ":"),
            )
        )
        return 0
    root = args.repo_root.resolve(strict=True)
    _require_stable_hooks(_codex_features())
    result = install(
        hooks_path=args.hooks_path,
        registry_path=args.registry_path,
        hooks_template_path=root / "templates" / "codex_hooks.json.template",
        registry_template_path=root / "templates" / "session_registry.json.template",
        adapter_path=root / "scripts" / "codex_session_adapter.py",
        python_executable=Path(sys.executable),
        backup_root=args.backup_root,
        codex_version=_codex_version(),
    )
    print(
        json.dumps(
            {
                "changed": result.changed,
                "manifest_path": (
                    str(result.manifest_path)
                    if result.manifest_path is not None
                    else None
                ),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
