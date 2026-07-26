#!/usr/bin/env python3
"""Shared, fail-open storage primitives for the session lifecycle hooks.

The scratch file records session intent. It is not repository truth and no
evidence gate may consume it as authority.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


SESSION_PLAN_SCHEMA = "session.plan.v1"
SESSION_REGISTRY_SCHEMA = "session.registry.v1"
SESSION_BINDING_SCHEMA = "session.binding.v1"

MAX_SESSION_PLAN_BYTES = 64 * 1024
MAX_SESSION_BINDING_BYTES = 64 * 1024
MAX_REGISTRY_BYTES = 128 * 1024
MAX_ERROR_LOG_BYTES = 128 * 1024
MAX_ERROR_LINE_CHARS = 1000

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REQUIRED_PLAN_TYPES: dict[str, type | tuple[type, ...]] = {
    "session_id": str,
    "goal": str,
    "chain": list,
    "persona": str,
    "risk": str,
    "repo": str,
    "start_sha": str,
    "checkpoints": list,
    "claims": list,
    "created_at": str,
    "updated_at": str,
}


@dataclass(frozen=True)
class RepositoryRegistration:
    """Validated registry entry bound to the current linked worktree."""

    name: str
    canonical_root: Path
    worktree_root: Path
    plan_paths: tuple[str, ...]
    vision_paths: tuple[str, ...]
    idea_paths: tuple[str, ...]


def _default_state_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_STATE_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "state"


def _default_registry_path() -> Path:
    override = os.environ.get("CLAUDE_SESSION_REGISTRY")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "session_registry.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("invalid session_id")
    return session_id


def _session_plan_path(session_id: str, state_dir: Path) -> Path:
    return state_dir / f"session_plan_{validate_session_id(session_id)}.json"


def session_binding_path(session_id: str, state_dir: Path) -> Path:
    return state_dir / f"session_binding_{validate_session_id(session_id)}.json"


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                # Windows can briefly hold the destination while another
                # reader or writer closes it. Keep the retry bounded.
                time.sleep(0.005 * (attempt + 1))
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def parse_nul_paths(payload: str) -> tuple[str, ...]:
    """Parse a NUL-delimited Git path list without interpreting path contents."""

    return tuple(dict.fromkeys(item for item in payload.split("\0") if item))


def parse_git_status_v2_z(payload: str) -> tuple[str, str, tuple[str, ...]]:
    """Return branch, HEAD and paths from ``git status --porcelain=v2 -z``."""

    branch = "unknown"
    head = ""
    paths: list[str] = []
    records = payload.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("# branch.head "):
            branch = record.removeprefix("# branch.head ").strip()
            continue
        if record.startswith("# branch.oid "):
            oid = record.removeprefix("# branch.oid ").strip()
            head = "" if oid == "(initial)" else oid
            continue
        if record.startswith(("? ", "! ")):
            paths.append(record[2:])
            continue
        if record.startswith("1 "):
            fields = record.split(" ", 8)
            if len(fields) == 9:
                paths.append(fields[8])
            continue
        if record.startswith("2 "):
            fields = record.split(" ", 9)
            if len(fields) == 10:
                paths.append(fields[9])
            # Porcelain v2 emits the original rename path as the next NUL
            # record. It is metadata, not a second current dirty path.
            if index < len(records):
                index += 1
            continue
        if record.startswith("u "):
            fields = record.split(" ", 10)
            if len(fields) == 11:
                paths.append(fields[10])
    return branch, head, tuple(dict.fromkeys(paths))


def _normalize_binding(raw: Any, expected_session_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("schema_version") != SESSION_BINDING_SCHEMA:
        return None
    required_strings = (
        "session_id",
        "repo",
        "worktree_root",
        "start_sha",
        "transcript_path",
        "start_branch",
        "created_at",
    )
    if any(not isinstance(raw.get(field), str) for field in required_strings):
        return None
    if raw["session_id"] != expected_session_id or not raw["repo"].strip():
        return None
    if raw["start_sha"] and not re.fullmatch(r"[0-9a-fA-F]{40}", raw["start_sha"]):
        return None
    dirty_paths = raw.get("start_dirty_paths")
    if not isinstance(dirty_paths, list) or not all(isinstance(item, str) for item in dirty_paths):
        return None
    try:
        worktree_root = Path(raw["worktree_root"]).expanduser()
        transcript_path = Path(raw["transcript_path"]).expanduser()
        if not worktree_root.is_absolute() or not transcript_path.is_absolute():
            return None
        normalized_root = worktree_root.resolve(strict=False)
        normalized_transcript = transcript_path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    normalized = dict(raw)
    normalized["worktree_root"] = str(normalized_root)
    normalized["transcript_path"] = str(normalized_transcript)
    normalized["start_dirty_paths"] = list(dict.fromkeys(dirty_paths))
    return normalized


def read_session_binding(
    session_id: str,
    *,
    state_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Read the immutable hook-owned provenance binding for one session."""

    target_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    try:
        safe_session_id = validate_session_id(session_id)
        path = session_binding_path(safe_session_id, target_dir)
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_SESSION_BINDING_BYTES:
            raise ValueError("session binding exceeds size bound")
        raw = json.loads(raw_bytes)
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        append_hook_error("SESSION_BINDING_INVALID", type(exc).__name__, state_dir=target_dir)
        return None

    normalized = _normalize_binding(raw, safe_session_id)
    if normalized is None:
        append_hook_error("SESSION_BINDING_INVALID", "schema validation", state_dir=target_dir)
    return normalized


def write_session_binding(
    session_id: str,
    payload: dict[str, Any],
    *,
    state_dir: Path | None = None,
) -> Path:
    """Create an immutable session provenance binding.

    A repeated identical write is idempotent. Any attempt to change an
    existing binding is rejected so model-editable scratch cannot redirect
    evidence collection.
    """

    target_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    safe_session_id = validate_session_id(session_id)
    normalized = _normalize_binding(payload, safe_session_id)
    if normalized is None:
        raise ValueError("invalid session binding")
    encoded = (
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_SESSION_BINDING_BYTES:
        raise ValueError("session binding exceeds size bound")
    path = session_binding_path(safe_session_id, target_dir)
    existing = read_session_binding(safe_session_id, state_dir=target_dir)
    if existing is not None:
        if existing != normalized:
            raise ValueError("immutable session binding mismatch")
        return path
    atomic_write_bytes(path, encoded)
    return path


def append_hook_error(
    code: str,
    detail: str = "",
    *,
    state_dir: Path | None = None,
) -> None:
    """Append one bounded diagnostic line without surfacing an exception."""

    target_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    path = target_dir / "hook_errors.log"
    safe_code = re.sub(r"[^A-Z0-9_.-]+", "_", str(code).upper())[:80] or "HOOK_ERROR"
    safe_detail = " ".join(str(detail).split())
    prefix = f"{_utc_now()} {safe_code}"
    available = max(0, MAX_ERROR_LINE_CHARS - len(prefix) - 1)
    line = f"{prefix} {safe_detail[:available]}".rstrip() + "\n"
    encoded = line.encode("utf-8", errors="replace")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        previous = b""
        try:
            previous = path.read_bytes()
        except FileNotFoundError:
            pass
        combined = previous + encoded
        if len(combined) > MAX_ERROR_LOG_BYTES:
            combined = combined[-MAX_ERROR_LOG_BYTES:]
            newline = combined.find(b"\n")
            combined = combined[newline + 1 :] if newline >= 0 else encoded[-MAX_ERROR_LOG_BYTES:]
        atomic_write_bytes(path, combined)
    except OSError:
        # Hooks fail open toward the session. The debug log is best-effort when
        # the state directory itself is unavailable.
        return


def _relative_paths(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        normalized = item.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(item)
        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
            return None
        result.append(posix.as_posix())
    return tuple(result)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.resolve(strict=False))))


def _load_registry(
    path: Path,
    *,
    state_dir: Path | None,
) -> list[dict[str, Any]] | None:
    try:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_REGISTRY_BYTES:
            raise ValueError("registry exceeds size bound")
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict) or raw.get("schema_version") != SESSION_REGISTRY_SCHEMA:
            raise ValueError("registry schema mismatch")
        repositories = raw.get("repositories")
        if not isinstance(repositories, list):
            raise ValueError("repositories must be a list")
        return repositories
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        append_hook_error("REGISTRY_INVALID", type(exc).__name__, state_dir=state_dir)
        return None


def resolve_repository(
    cwd: str | Path,
    *,
    registry_path: Path | None = None,
    state_dir: Path | None = None,
    git_timeout_s: float = 0.75,
) -> RepositoryRegistration | None:
    """Resolve a registered repository with exactly one bounded git spawn."""

    registry = _load_registry(
        Path(registry_path) if registry_path is not None else _default_registry_path(),
        state_dir=state_dir,
    )
    if registry is None:
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(Path(cwd)),
                "rev-parse",
                "--show-toplevel",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=git_timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        append_hook_error("GIT_RESOLVE_FAILED", type(exc).__name__, state_dir=state_dir)
        return None
    if result.returncode != 0:
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        append_hook_error("GIT_RESOLVE_INVALID", "missing rev-parse fields", state_dir=state_dir)
        return None
    worktree_root = Path(lines[0]).resolve(strict=False)
    common_git_dir = Path(lines[1]).resolve(strict=False)
    common_root = common_git_dir.parent if common_git_dir.name.lower() == ".git" else common_git_dir
    candidate_keys = {_path_key(worktree_root), _path_key(common_root)}

    for entry in registry:
        try:
            if not isinstance(entry, dict):
                raise ValueError("entry is not an object")
            name = entry.get("name")
            root_raw = entry.get("root")
            if not isinstance(name, str) or not name.strip() or not isinstance(root_raw, str):
                raise ValueError("entry name/root invalid")
            configured_root = Path(root_raw).expanduser()
            if not configured_root.is_absolute():
                raise ValueError("entry root must be absolute")
            canonical_root = configured_root.resolve(strict=False)
            plan_paths = _relative_paths(entry.get("plan_paths", []))
            vision_paths = _relative_paths(entry.get("vision_paths", []))
            idea_paths = _relative_paths(entry.get("idea_paths", []))
            if plan_paths is None or vision_paths is None or idea_paths is None:
                raise ValueError("entry paths must be safe relative paths")
        except (OSError, ValueError, TypeError) as exc:
            append_hook_error("REGISTRY_INVALID", type(exc).__name__, state_dir=state_dir)
            return None

        if _path_key(canonical_root) in candidate_keys:
            return RepositoryRegistration(
                name=name.strip(),
                canonical_root=canonical_root,
                worktree_root=worktree_root,
                plan_paths=plan_paths,
                vision_paths=vision_paths,
                idea_paths=idea_paths,
            )
    return None


def _normalize_plan(raw: Any, expected_session_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("schema_version") != SESSION_PLAN_SCHEMA:
        return None
    for field, expected_type in _REQUIRED_PLAN_TYPES.items():
        if not isinstance(raw.get(field), expected_type):
            return None
    if raw["session_id"] != expected_session_id:
        return None
    if not all(isinstance(item, str) for item in raw["chain"]):
        return None
    if raw["risk"] not in {"", "R0", "R1", "R2", "R3"}:
        return None
    transcript_path = raw.get("transcript_path")
    if transcript_path is not None and not isinstance(transcript_path, str):
        return None
    normalized = dict(raw)
    normalized["transcript_path"] = transcript_path or None
    return normalized


def read_session_plan(
    session_id: str,
    *,
    state_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Read and validate a scratch file; malformed input is treated as absent."""

    target_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    try:
        path = _session_plan_path(session_id, target_dir)
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_SESSION_PLAN_BYTES:
            raise ValueError("session plan exceeds size bound")
        raw = json.loads(raw_bytes)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        append_hook_error("SESSION_PLAN_INVALID", type(exc).__name__, state_dir=target_dir)
        return None

    if isinstance(raw, dict) and raw.get("schema_version") != SESSION_PLAN_SCHEMA:
        append_hook_error(
            "UNRECOGNIZED_VERSION",
            str(raw.get("schema_version", "missing"))[:80],
            state_dir=target_dir,
        )
        return None

    normalized = _normalize_plan(raw, session_id)
    if normalized is None:
        append_hook_error("SESSION_PLAN_INVALID", "schema validation", state_dir=target_dir)
    return normalized


def write_session_plan(
    session_id: str,
    payload: dict[str, Any],
    *,
    state_dir: Path | None = None,
) -> Path:
    """Validate and atomically replace one session scratch file."""

    target_dir = Path(state_dir) if state_dir is not None else _default_state_dir()
    safe_session_id = validate_session_id(session_id)
    normalized = _normalize_plan(payload, safe_session_id)
    if normalized is None:
        raise ValueError("invalid session plan")
    encoded = (
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_SESSION_PLAN_BYTES:
        raise ValueError("session plan exceeds size bound")
    path = _session_plan_path(safe_session_id, target_dir)
    atomic_write_bytes(path, encoded)
    return path
