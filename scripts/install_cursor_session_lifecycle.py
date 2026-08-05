#!/usr/bin/env python3
"""Install the global Cursor Agent CLI lifecycle hook (~/.cursor/hooks.json).

CU3 of design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md:
"implement and test idempotent user-level install/rollback."

Scope is CLI-only, sessionStart + sessionEnd only, matching the plan's proven CU0-L
evidence: Cursor Agent CLI context delivery and lifecycle pairing were promoted to
CU1; Cursor IDE remains HOLD DEGRADED (root-identity unproven on second start);
preCompact remains UNPROVEN_NO_DETERMINISTIC_TRIGGER on both surfaces. Wiring is
therefore deliberately narrower than the full event set the adapter (CU1,
scripts/cursor_session_adapter.py) already supports -- IDE sessions that fire the
shared hooks.json are already a safe no-op there via the adapter's own CLI-version
gate (CURSOR_ADAPTER_UNSUPPORTED_SURFACE), so sharing one hooks.json file for both
surfaces does not grant IDE full lifecycle treatment.

Cursor's hooks.json schema is FLAT (unlike Claude/Codex's nested matcher-group
shape): hooks.<event> is a list of handler objects directly
({command, type?, matcher?, timeout?, failClosed?, loop_limit?}), verified against
~/.cursor/skills-cursor/create-hook/SKILL.md. commandWindows is not a documented
Cursor field, so this installer uses the same simple, proven invocation idiom
already live for Claude (scripts/hooks_install.py render_command): `<interpreter>
"<absolute posix path>"`, not Codex's PowerShell -EncodedCommand wrapping (no
evidence that convention is required or even supported by Cursor's hook runner).

CU3 builds and tests install/rollback against temporary homes only. It never
mutates the operator's real ~/.cursor/hooks.json unless invoked with --apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooks_install import _command_path_token, render_command  # noqa: E402 - reuse proven helpers
from cursor_session_adapter import _CURSOR_CLI_VERSION_RE  # noqa: E402 - single source of the version shape
from session_state import atomic_write_bytes  # noqa: E402

ADAPTER_NAME = "cursor_session_adapter.py"
REQUIRED_EVENTS = ("sessionStart", "sessionEnd")
MANIFEST_SCHEMA = "cursor.session.lifecycle.install.v1"


class PreflightError(ValueError):
    """Raised when the installed Cursor Agent CLI version is missing or unsupported."""


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
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


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


def _restore_if_installed(path: Path, *, installed: bytes, previous: bytes | None) -> bool:
    if _read_optional(path) != installed:
        return False
    _restore_target(path, previous)
    return True


def _references_adapter(command: object) -> bool:
    """Anchored ownership check (CU3 requirement 3: "refuse malformed/ambiguous
    ownership"). A bare substring match would misclassify any foreign command that
    merely mentions our filename (e.g. a comment, an unrelated echo) as owned, and
    silently drop it on reinstall. Extract the quote-aware path token and require
    its exact basename to equal the adapter filename; a command that cannot be
    confidently tokenized is treated as foreign (never claimed, never dropped)."""
    if not isinstance(command, str):
        return False
    token = _command_path_token(command)
    if token is None:
        return False
    return Path(token.replace("\\", "/")).name == ADAPTER_NAME


def _preflight_cli_version(cursor_agent: Path | None = None) -> str:
    """Locate the Cursor Agent CLI and validate its --version output matches the
    exact shape the shipped adapter (CU1) already recognizes at runtime
    (_CURSOR_CLI_VERSION_RE). Fail closed: missing executable, non-zero exit,
    timeout, or an unrecognized version shape all raise PreflightError with no
    mutation performed by the caller. This is CU3 requirement 1."""
    exe = cursor_agent
    if exe is None:
        found = shutil.which("cursor-agent")
        if found is None:
            raise PreflightError("cursor-agent executable not found on PATH")
        exe = Path(found)
    try:
        proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                              timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"cursor-agent --version failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise PreflightError(f"cursor-agent --version exited {proc.returncode}")
    version = proc.stdout.strip()
    if not _CURSOR_CLI_VERSION_RE.fullmatch(version):
        raise PreflightError(f"unsupported cursor-agent version shape: {version!r}")
    return version


def _merge_hooks(existing: dict[str, Any] | None, command: str) -> dict[str, Any]:
    """Handler-level merge on Cursor's FLAT schema: hooks.<event> is a list of
    handler dicts directly. Preserve every foreign handler (one not referencing
    our adapter); replace/insert exactly one owned handler per required event."""
    base: dict[str, Any] = {"version": 1, "hooks": {}}
    if existing is not None:
        if existing.get("version") not in (None, 1):
            raise ValueError(f"unsupported Cursor hooks.json version: {existing.get('version')!r}")
        existing_hooks = existing.get("hooks")
        if existing_hooks is not None and not isinstance(existing_hooks, dict):
            raise ValueError("existing hooks.json 'hooks' must be an object")
        if isinstance(existing_hooks, dict):
            base["hooks"] = json.loads(json.dumps(existing_hooks))  # structural deep copy
        for key, value in existing.items():
            if key not in ("version", "hooks"):
                base[key] = value

    for event in REQUIRED_EVENTS:
        group = base["hooks"].get(event, [])
        if not isinstance(group, list):
            raise ValueError(f"existing hooks.json hooks.{event} must be an array")
        foreign = [h for h in group if not (isinstance(h, dict) and _references_adapter(h.get("command")))]
        foreign.append({"command": command, "timeout": 5})
        base["hooks"][event] = foreign
    return base


def install(
    *,
    hooks_path: Path,
    hooks_template_path: Path,
    adapter_path: Path,
    python_executable: Path,
    backup_root: Path,
    cursor_agent: Path | None = None,
    skip_cli_preflight: bool = False,
) -> InstallResult:
    """Install the rendered Cursor hook and record its provenance. Dry semantics
    are the caller's responsibility (fresh home == dry apply; the CLI --apply flag
    gates real-machine mutation). CU3 requirement 1: preflight the installed CLI
    version and reject an unsupported schema before any mutation. skip_cli_preflight
    exists only for tests that exercise merge/rollback logic in isolation from a
    real cursor-agent binary; the CLI entrypoint never sets it."""
    if not skip_cli_preflight:
        _preflight_cli_version(cursor_agent)
    adapter = adapter_path.resolve(strict=True)  # raises if the adapter script is absent
    interpreter = python_executable.resolve(strict=True)
    command = render_command(str(interpreter), adapter.parents[1], adapter.name)

    template = _json(hooks_template_path)
    if template.get("version") != 1:
        raise ValueError("cursor hooks template must declare version 1")
    for event in REQUIRED_EVENTS:
        if event not in template.get("hooks", {}):
            raise ValueError(f"cursor hooks template is missing required event: {event}")

    previous_hooks = _read_optional(hooks_path)
    existing = json.loads(previous_hooks) if previous_hooks is not None else None
    if existing is not None and not isinstance(existing, dict):
        raise ValueError("existing hooks.json must contain a JSON object")

    merged = _merge_hooks(existing, command)
    hooks_bytes = _encoded(merged)
    changed = previous_hooks != hooks_bytes
    if not changed:
        return InstallResult(changed=False, manifest_path=None)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_dir = backup_root / f"cursor-session-lifecycle-{stamp}"
    hooks_backup = manifest_dir / "hooks.before.json"
    if previous_hooks is not None:
        atomic_write_bytes(hooks_backup, previous_hooks)

    try:
        _assert_unchanged(hooks_path, previous_hooks, label="hooks")
        atomic_write_bytes(hooks_path, hooks_bytes)
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
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
            },
            "rollback_command": f'{interpreter} "{Path(__file__).resolve()}" --rollback '
                                 f'"{manifest_dir / "install_manifest.json"}"',
        }
        manifest_path = manifest_dir / "install_manifest.json"
        atomic_write_bytes(manifest_path, _encoded(manifest))
    except BaseException:
        _restore_if_installed(hooks_path, installed=hooks_bytes, previous=previous_hooks)
        raise
    return InstallResult(changed=True, manifest_path=manifest_path)


def rollback(
    manifest_path: Path,
    *,
    allowed_backup_root: Path | None = None,
    expected_hooks_path: Path | None = None,
) -> None:
    """Restore the hooks target only while it still matches the installed hash."""
    manifest_path = manifest_path.resolve(strict=True)
    if (
        allowed_backup_root is not None
        and manifest_path.parent.parent != allowed_backup_root.resolve(strict=False)
    ):
        raise ValueError("install manifest is outside the allowed backup root")
    manifest = _json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("install manifest schema mismatch")
    target = manifest.get("targets", {}).get("hooks")
    if not isinstance(target, dict) or not isinstance(target.get("path"), str):
        raise ValueError("manifest target 'hooks' is invalid")
    path = Path(target["path"]).resolve(strict=False)
    if expected_hooks_path is not None and path != expected_hooks_path.resolve(strict=False):
        raise ValueError("manifest target does not match configured hooks path")
    current = _read_optional(path)
    if _sha256(current) != target.get("installed_sha256"):
        raise ValueError("installed target changed since activation: hooks")
    existed = target.get("existed")
    backup_raw = target.get("backup_path")
    if existed is True:
        if not isinstance(backup_raw, str):
            raise ValueError("manifest backup is missing: hooks")
        backup_path = Path(backup_raw).resolve(strict=False)
        if allowed_backup_root is not None and backup_path.parent.parent != allowed_backup_root.resolve(strict=False):
            raise ValueError("backup path is outside the allowed backup root")
        previous = _read_optional(backup_path)
        if previous is None or target.get("before_sha256") != _sha256(previous):
            raise ValueError("backup content does not match recorded before-hash: hooks")
    elif existed is False:
        previous = None
    else:
        raise ValueError("manifest target 'existed' flag is invalid: hooks")
    _restore_target(path, previous)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", type=Path, help="restore the target recorded in an install manifest")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--hooks-path", type=Path, default=Path.home() / ".cursor" / "hooks.json")
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".cursor" / "backups")
    parser.add_argument("--apply", action="store_true",
                        help="perform the install (omit for a dry-run diff only)")
    args = parser.parse_args()

    if args.rollback is not None:
        rollback(args.rollback, allowed_backup_root=args.backup_root, expected_hooks_path=args.hooks_path)
        print(json.dumps({"rolled_back": True, "manifest_path": str(args.rollback)}, separators=(",", ":")))
        return 0

    root = args.repo_root.resolve(strict=True)
    adapter_path = root / "scripts" / ADAPTER_NAME
    template_path = root / "templates" / "cursor_hooks.json.template"

    if not args.apply:
        previous = _read_optional(args.hooks_path)
        interpreter = Path(sys.executable).resolve(strict=True)
        command = render_command(str(interpreter), root, ADAPTER_NAME)
        existing = json.loads(previous) if previous is not None else None
        merged = _merge_hooks(existing, command)
        try:
            cli_version = _preflight_cli_version()
            cli_supported = True
        except PreflightError as exc:
            cli_version = None
            cli_supported = False
            preflight_error = str(exc)
        print(json.dumps({
            "mode": "dry-run",
            "hooks_path": str(args.hooks_path),
            "would_change": previous != _encoded(merged),
            "rendered_command": command,
            "cli_version": cli_version,
            "cli_supported": cli_supported,
            **({} if cli_supported else {"cli_preflight_error": preflight_error}),
        }, indent=2))
        return 0

    args.backup_root.mkdir(parents=True, exist_ok=True)
    result = install(
        hooks_path=args.hooks_path,
        hooks_template_path=template_path,
        adapter_path=adapter_path,
        python_executable=Path(sys.executable),
        backup_root=args.backup_root,
    )
    print(json.dumps({
        "changed": result.changed,
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
