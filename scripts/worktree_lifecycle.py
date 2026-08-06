#!/usr/bin/env python3
"""Bounded worktree custody records and exact-gated terminal cleanup.

Session hooks call only :func:`record_session_start` and
:func:`record_session_close`. Those functions are report-only and fail open.
The CLI ``apply`` command is the sole mutating path; it requires an exact
receipt-derived authorization and revalidates the target immediately before
removal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from session_state import (
    append_hook_error,
    atomic_write_bytes,
    parse_git_status_v2_z,
    validate_session_id,
)


RECORD_SCHEMA = "worktree.lifecycle.record.v1"
MUTATION_SCHEMA = "worktree.lifecycle.mutation.v1"
MAX_RECORD_BYTES = 64 * 1024
GIT_TIMEOUT_S = 2.0
HOOK_GIT_TIMEOUT_S = 0.35

PRESERVE_PRIMARY = "PRESERVE_PRIMARY"
DIRTY_CUSTODY = "DIRTY_CUSTODY"
LOCKED_CUSTODY = "LOCKED_CUSTODY"
COMMITTED_UNMERGED_CUSTODY = "COMMITTED_UNMERGED_CUSTODY"
ELIGIBLE_MERGED_REMOVE = "ELIGIBLE_MERGED_REMOVE"
ELIGIBLE_DETACHED_REMOVE = "ELIGIBLE_DETACHED_REMOVE"
UNKNOWN_PRESERVE = "UNKNOWN_PRESERVE"
ACTIVE = "ACTIVE"

ELIGIBLE_DISPOSITIONS = {
    ELIGIBLE_MERGED_REMOVE,
    ELIGIBLE_DETACHED_REMOVE,
}


@dataclass(frozen=True)
class WorktreeMetadata:
    root: str
    head: str
    branch: str | None
    primary: bool
    locked: bool
    lock_reason: str
    prunable: bool
    prune_reason: str


@dataclass(frozen=True)
class FreshSnapshot:
    root: str
    head: str
    branch: str
    dirty_paths: tuple[str, ...]
    metadata: WorktreeMetadata | None
    base_ref: str | None
    work_reached_trunk: bool | None
    git_ok: bool


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _path_key(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _default_state_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_STATE_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "state"


def _run_git(
    repo: str | Path,
    args: Iterable[str],
    *,
    timeout_s: float = GIT_TIMEOUT_S,
    allowed_returncodes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )
    allowed = allowed_returncodes or {0}
    if result.returncode not in allowed:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise RuntimeError(f"git exit={result.returncode}: {detail}")
    return result


def parse_worktree_porcelain(payload: str) -> tuple[WorktreeMetadata, ...]:
    """Parse ``git worktree list --porcelain`` without path guessing."""

    rows: list[WorktreeMetadata] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        root = current.get("root")
        if isinstance(root, str) and root:
            rows.append(
                WorktreeMetadata(
                    root=str(Path(root).resolve(strict=False)),
                    head=str(current.get("head") or ""),
                    branch=current.get("branch"),
                    primary=not rows,
                    locked=bool(current.get("locked", False)),
                    lock_reason=str(current.get("lock_reason") or ""),
                    prunable=bool(current.get("prunable", False)),
                    prune_reason=str(current.get("prune_reason") or ""),
                )
            )
        current = None

    for raw_line in payload.splitlines():
        line = raw_line.rstrip("\r\n")
        if line.startswith("worktree "):
            flush()
            current = {"root": line.removeprefix("worktree ")}
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current["head"] = line.removeprefix("HEAD ").strip()
        elif line.startswith("branch "):
            current["branch"] = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif line == "detached":
            current["branch"] = None
        elif line.startswith("locked"):
            current["locked"] = True
            current["lock_reason"] = line.removeprefix("locked").strip()
        elif line.startswith("prunable"):
            current["prunable"] = True
            current["prune_reason"] = line.removeprefix("prunable").strip()
        elif not line:
            flush()
    flush()
    return tuple(rows)


def read_worktree_metadata(
    repo: str | Path,
    *,
    timeout_s: float = GIT_TIMEOUT_S,
) -> WorktreeMetadata | None:
    root_key = _path_key(repo)
    payload = _run_git(
        repo,
        ["worktree", "list", "--porcelain"],
        timeout_s=timeout_s,
    ).stdout
    for entry in parse_worktree_porcelain(payload):
        if _path_key(entry.root) == root_key:
            return entry
    return None


def read_current_worktree_metadata(
    repo: str | Path,
    *,
    head: str,
    branch: str,
    timeout_s: float = HOOK_GIT_TIMEOUT_S,
) -> WorktreeMetadata:
    """Read only the current checkout metadata without scanning every worktree."""

    root = str(Path(repo).resolve(strict=False))
    result = _run_git(
        root,
        ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        timeout_s=timeout_s,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise RuntimeError("git-dir probe returned unexpected output")
    git_dir = Path(lines[0]).resolve(strict=False)
    common_dir = Path(lines[1]).resolve(strict=False)
    locked_path = git_dir / "locked"
    lock_reason = ""
    if locked_path.is_file():
        lock_reason = locked_path.read_text(encoding="utf-8", errors="replace")[:500].strip()
    return WorktreeMetadata(
        root=root,
        head=str(head),
        branch=None if branch in {"", "(detached)", "HEAD"} else str(branch),
        primary=_path_key(git_dir) == _path_key(common_dir),
        locked=locked_path.is_file(),
        lock_reason=lock_reason,
        prunable=False,
        prune_reason="",
    )


def resolve_base_ref(repo: str | Path) -> str | None:
    for candidate in ("origin/main", "origin/master", "main", "master"):
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", candidate],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    return None


def capture_fresh_snapshot(repo: str | Path) -> FreshSnapshot:
    root = str(Path(repo).resolve(strict=False))
    try:
        status = _run_git(
            root,
            ["status", "--porcelain=v2", "--branch", "--untracked-files=normal", "-z"],
        )
        branch, head, dirty_paths = parse_git_status_v2_z(status.stdout)
        metadata = read_worktree_metadata(root)
        base_ref = resolve_base_ref(root)
        reached: bool | None = None
        if head and base_ref is not None:
            ancestor = _run_git(
                root,
                ["merge-base", "--is-ancestor", "HEAD", base_ref],
                allowed_returncodes={0, 1},
            )
            reached = ancestor.returncode == 0
        return FreshSnapshot(
            root=root,
            head=head,
            branch=branch,
            dirty_paths=dirty_paths,
            metadata=metadata,
            base_ref=base_ref,
            work_reached_trunk=reached,
            git_ok=bool(head) and metadata is not None,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return FreshSnapshot(root, "", "unknown", (), None, None, None, False)


def classify_terminal(
    *,
    git_ok: bool,
    dirty_paths: Iterable[str],
    work_reached_trunk: bool | None,
    metadata: WorktreeMetadata | None,
) -> str:
    if not git_ok or metadata is None or work_reached_trunk is None:
        return UNKNOWN_PRESERVE
    if metadata.primary:
        return PRESERVE_PRIMARY
    if metadata.prunable:
        return UNKNOWN_PRESERVE
    if metadata.locked:
        return LOCKED_CUSTODY
    if any(True for _ in dirty_paths):
        return DIRTY_CUSTODY
    if metadata.branch is None:
        return ELIGIBLE_DETACHED_REMOVE
    if work_reached_trunk:
        return ELIGIBLE_MERGED_REMOVE
    return COMMITTED_UNMERGED_CUSTODY


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def receipt_sha256(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_payload(unsigned)).hexdigest().upper()


def _record_path(state_dir: Path, session_id: str, event: str) -> Path:
    return state_dir / "worktree_lifecycle" / f"session_{session_id}_{event}.json"


def _current_path(state_dir: Path, root: str | Path) -> Path:
    digest = hashlib.sha256(_path_key(root).encode("utf-8")).hexdigest()[:24]
    return state_dir / "worktree_lifecycle" / f"worktree_{digest}.json"


def _write_record(payload: dict[str, Any], *, state_dir: Path) -> Path:
    digest = receipt_sha256(payload)
    signed = {**payload, "receipt_sha256": digest}
    encoded = _canonical_payload(signed) + b"\n"
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError("worktree lifecycle record exceeds size bound")
    session_id = validate_session_id(str(signed["session_id"]))
    event = str(signed["event"])
    history_path = _record_path(state_dir, session_id, event)
    atomic_write_bytes(history_path, encoded)
    atomic_write_bytes(_current_path(state_dir, str(signed["worktree_root"])), encoded)
    return history_path


def _metadata_dict(metadata: WorktreeMetadata | None) -> dict[str, Any] | None:
    return asdict(metadata) if metadata is not None else None


def record_session_start(
    *,
    session_id: str,
    repo: str,
    worktree_root: str | Path,
    head: str,
    branch: str,
    dirty_paths: Iterable[str],
    owner_runtime: str,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> Path | None:
    target_state = Path(state_dir) if state_dir is not None else _default_state_dir()
    try:
        safe_id = validate_session_id(session_id)
        metadata = read_current_worktree_metadata(
            worktree_root,
            head=head,
            branch=branch,
            timeout_s=HOOK_GIT_TIMEOUT_S,
        )
        payload: dict[str, Any] = {
            "schema_version": RECORD_SCHEMA,
            "event": "start",
            "session_id": safe_id,
            "repo": str(repo),
            "worktree_root": str(Path(worktree_root).resolve(strict=False)),
            "head": str(head),
            "branch": str(branch),
            "dirty_paths": sorted({str(path) for path in dirty_paths})[:5000],
            "owner_runtime": str(owner_runtime)[:80],
            "disposition": ACTIVE,
            "work_reached_trunk": None,
            "metadata": _metadata_dict(metadata),
            "recorded_at": _iso(now),
        }
        return _write_record(payload, state_dir=target_state)
    except Exception as exc:  # noqa: BLE001 - hook recorder is fail-open
        append_hook_error("WORKTREE_START_RECORD_FAILED", type(exc).__name__, state_dir=target_state)
        return None


def record_session_close(
    *,
    session_id: str,
    repo: str,
    worktree_root: str | Path,
    head: str,
    branch: str,
    dirty_paths: Iterable[str],
    work_reached_trunk: bool | None,
    git_ok: bool,
    owner_runtime: str,
    lifecycle_verdict: str,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> Path | None:
    target_state = Path(state_dir) if state_dir is not None else _default_state_dir()
    try:
        safe_id = validate_session_id(session_id)
        metadata = read_current_worktree_metadata(
            worktree_root,
            head=head,
            branch=branch,
            timeout_s=HOOK_GIT_TIMEOUT_S,
        )
        paths = tuple(sorted({str(path) for path in dirty_paths}))
        disposition = classify_terminal(
            git_ok=git_ok,
            dirty_paths=paths,
            work_reached_trunk=work_reached_trunk,
            metadata=metadata,
        )
        payload: dict[str, Any] = {
            "schema_version": RECORD_SCHEMA,
            "event": "close",
            "session_id": safe_id,
            "repo": str(repo),
            "worktree_root": str(Path(worktree_root).resolve(strict=False)),
            "head": str(head),
            "branch": str(branch),
            "dirty_paths": list(paths[:5000]),
            "owner_runtime": str(owner_runtime)[:80],
            "disposition": disposition,
            "work_reached_trunk": work_reached_trunk,
            "metadata": _metadata_dict(metadata),
            "lifecycle_verdict": str(lifecycle_verdict)[:40],
            "recorded_at": _iso(now),
        }
        return _write_record(payload, state_dir=target_state)
    except Exception as exc:  # noqa: BLE001 - hook recorder is fail-open
        append_hook_error("WORKTREE_CLOSE_RECORD_FAILED", type(exc).__name__, state_dir=target_state)
        return None


def load_receipt(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("receipt exceeds size bound")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != RECORD_SCHEMA:
        raise ValueError("receipt schema mismatch")
    actual = payload.get("receipt_sha256")
    expected = receipt_sha256(payload)
    if not isinstance(actual, str) or actual.upper() != expected:
        raise ValueError("receipt hash mismatch")
    return payload


def _authorization_for(receipt: dict[str, Any]) -> str:
    return f"GO WORKTREE APPLY {receipt['receipt_sha256']}"


def _common_repo_root(root: str | Path) -> Path:
    output = _run_git(
        root,
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
    ).stdout.strip()
    common = Path(output).resolve(strict=False)
    return common.parent if common.name.lower() == ".git" else common


def _write_mutation_receipt(
    payload: dict[str, Any],
    *,
    receipt_path: str | Path,
    receipt_sha256_value: str,
    mutation_dir: Path | None,
) -> Path:
    unsigned = dict(payload)
    unsigned.pop("mutation_sha256", None)
    signed = {
        **unsigned,
        "mutation_sha256": hashlib.sha256(
            _canonical_payload(unsigned)
        ).hexdigest().upper(),
    }
    encoded = _canonical_payload(signed) + b"\n"
    target_dir = mutation_dir or Path(receipt_path).resolve(strict=False).parent
    target = target_dir / f"mutation_{receipt_sha256_value[:24]}.json"
    atomic_write_bytes(target, encoded)
    return target


def apply_receipt(
    receipt_path: str | Path,
    *,
    authorization: str,
    mutation_dir: Path | None = None,
    now: datetime | None = None,
) -> Path:
    receipt = load_receipt(receipt_path)
    if receipt.get("event") != "close" or receipt.get("disposition") not in ELIGIBLE_DISPOSITIONS:
        raise ValueError("receipt is not eligible for removal")
    if authorization != _authorization_for(receipt):
        raise PermissionError("exact receipt authorization required")

    root = Path(str(receipt["worktree_root"])).resolve(strict=False)
    try:
        Path.cwd().resolve(strict=False).relative_to(root)
    except ValueError:
        pass
    else:
        raise RuntimeError("apply must run outside the target worktree")

    fresh = capture_fresh_snapshot(root)
    disposition = classify_terminal(
        git_ok=fresh.git_ok,
        dirty_paths=fresh.dirty_paths,
        work_reached_trunk=fresh.work_reached_trunk,
        metadata=fresh.metadata,
    )
    if disposition != receipt["disposition"]:
        raise RuntimeError(f"stale receipt disposition: {receipt['disposition']} -> {disposition}")
    if _path_key(fresh.root) != _path_key(root):
        raise RuntimeError("fresh root mismatch")
    if fresh.head != receipt.get("head") or fresh.branch != receipt.get("branch"):
        raise RuntimeError("stale receipt HEAD or branch")
    metadata = fresh.metadata
    if metadata is None or metadata.primary or metadata.locked or metadata.prunable:
        raise RuntimeError("fresh worktree metadata is not removable")

    common_root = _common_repo_root(root)
    remove_argv = ["git", "worktree", "remove", "--", str(root)]
    branch_argv = (
        ["git", "branch", "-d", "--", metadata.branch]
        if metadata.branch is not None
        else None
    )
    mutation_payload = {
        "schema_version": MUTATION_SCHEMA,
        "source_receipt": str(Path(receipt_path).resolve(strict=False)),
        "source_receipt_sha256": receipt["receipt_sha256"],
        "worktree_root": str(root),
        "head": fresh.head,
        "branch": metadata.branch,
        "status": "PREPARED",
        "worktree_removed": False,
        "remove_error": None,
        "branch_deleted": False,
        "branch_delete_error": None,
        "commands": [
            {"argv": remove_argv, "exit": None},
            *([{"argv": branch_argv, "exit": None}] if branch_argv is not None else []),
        ],
        "prepared_at": _iso(now),
        "completed_at": None,
    }
    target = _write_mutation_receipt(
        mutation_payload,
        receipt_path=receipt_path,
        receipt_sha256_value=receipt["receipt_sha256"],
        mutation_dir=mutation_dir,
    )

    try:
        remove = _run_git(
            common_root,
            remove_argv[1:],
            timeout_s=15.0,
            allowed_returncodes=set(range(256)),
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        mutation_payload["status"] = "FAILED_REMOVE"
        mutation_payload["remove_error"] = type(exc).__name__
        mutation_payload["completed_at"] = _iso(now)
        _write_mutation_receipt(
            mutation_payload,
            receipt_path=receipt_path,
            receipt_sha256_value=receipt["receipt_sha256"],
            mutation_dir=mutation_dir,
        )
        raise RuntimeError(f"worktree removal failed; mutation={target}") from exc
    mutation_payload["commands"][0]["exit"] = remove.returncode
    mutation_payload["worktree_removed"] = remove.returncode == 0
    if remove.returncode != 0:
        mutation_payload["status"] = "FAILED_REMOVE"
        mutation_payload["remove_error"] = (remove.stderr or remove.stdout).strip()[:500]
        mutation_payload["completed_at"] = _iso(now)
        _write_mutation_receipt(
            mutation_payload,
            receipt_path=receipt_path,
            receipt_sha256_value=receipt["receipt_sha256"],
            mutation_dir=mutation_dir,
        )
        raise RuntimeError(f"worktree removal failed; mutation={target}")

    if metadata.branch is not None and branch_argv is not None:
        try:
            delete = _run_git(
                common_root,
                branch_argv[1:],
                timeout_s=10.0,
                allowed_returncodes=set(range(256)),
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            mutation_payload["status"] = "PARTIAL_BRANCH_RETAINED"
            mutation_payload["branch_delete_error"] = type(exc).__name__
            mutation_payload["completed_at"] = _iso(now)
            _write_mutation_receipt(
                mutation_payload,
                receipt_path=receipt_path,
                receipt_sha256_value=receipt["receipt_sha256"],
                mutation_dir=mutation_dir,
            )
            raise RuntimeError(
                f"worktree removed but branch deletion failed; mutation={target}"
            ) from exc
        mutation_payload["commands"][1]["exit"] = delete.returncode
        mutation_payload["branch_deleted"] = delete.returncode == 0
        if delete.returncode != 0:
            mutation_payload["status"] = "PARTIAL_BRANCH_RETAINED"
            mutation_payload["branch_delete_error"] = (
                delete.stderr or delete.stdout
            ).strip()[:500]
            mutation_payload["completed_at"] = _iso(now)
            _write_mutation_receipt(
                mutation_payload,
                receipt_path=receipt_path,
                receipt_sha256_value=receipt["receipt_sha256"],
                mutation_dir=mutation_dir,
            )
            raise RuntimeError(f"worktree removed but branch deletion failed; mutation={target}")

    mutation_payload["status"] = "APPLIED"
    mutation_payload["completed_at"] = _iso(now)
    target = _write_mutation_receipt(
        mutation_payload,
        receipt_path=receipt_path,
        receipt_sha256_value=receipt["receipt_sha256"],
        mutation_dir=mutation_dir,
    )
    return target


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_parser = sub.add_parser("inspect", help="print a fresh report-only snapshot")
    inspect_parser.add_argument("--repo", required=True)
    apply_parser = sub.add_parser("apply", help="apply one exact terminal receipt")
    apply_parser.add_argument("--receipt", required=True)
    apply_parser.add_argument("--authorization", required=True)
    apply_parser.add_argument("--mutation-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "inspect":
        snapshot = capture_fresh_snapshot(args.repo)
        disposition = classify_terminal(
            git_ok=snapshot.git_ok,
            dirty_paths=snapshot.dirty_paths,
            work_reached_trunk=snapshot.work_reached_trunk,
            metadata=snapshot.metadata,
        )
        print(
            json.dumps(
                {**asdict(snapshot), "disposition": disposition},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    target = apply_receipt(
        args.receipt,
        authorization=args.authorization,
        mutation_dir=Path(args.mutation_dir) if args.mutation_dir else None,
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
