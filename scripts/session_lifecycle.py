#!/usr/bin/env python3
"""Persist a fail-closed, session-attributed verdict at SessionEnd."""

from __future__ import annotations

import json
import heapq
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from session_state import (
    RepositoryRegistration,
    append_hook_error,
    atomic_write_bytes,
    parse_git_status_v2_z,
    parse_nul_paths,
    read_session_binding,
    read_session_plan,
    resolve_repository,
    validate_session_id,
)
from transcript_projection import (
    project_record,
    projection_complete,
    write_path_candidates,
)


VERDICT_SCHEMA = "session.verdict.v1"
MAX_VERDICT_BYTES = 64 * 1024
MAX_TRANSCRIPT_SCAN_BYTES = 4 * 1024 * 1024
SESSION_END_WORK_DEADLINE_S = 1.2
VERDICT_VALUES = {"NO-OP", "ARCHIVE-OK", "HANDOFF", "CHECKPOINT", "UNKNOWN"}
_MAX_PENDING_RESULTS = 400
_VERDICT_LOCK_TIMEOUT_S = 0.2
_VERDICT_LOCK_STALE_S = 5.0

_CLOSED_STATUSES = {"done", "closed", "complete", "completed", "resolved", "shipped"}


@dataclass(frozen=True)
class SessionEvidence:
    git_ok: bool
    head: str
    branch: str
    dirty_paths: tuple[str, ...]
    commit_shas: tuple[str, ...]
    committed_paths: tuple[str, ...]
    transcript_written_paths: tuple[str, ...]
    transcript_complete: bool
    work_reached_trunk: bool | None


@dataclass(frozen=True)
class VerdictDecision:
    verdict: str
    reason: str
    attributable_paths: tuple[str, ...]
    open_items: tuple[str, ...]


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _default_state_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_STATE_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "state"


def _safe_session_id(value: object) -> str:
    return validate_session_id(value)


def _verdict_path(session_id: str, state_dir: Path) -> Path:
    return state_dir / f"session_verdict_{_safe_session_id(session_id)}.json"


@contextmanager
def _verdict_lock(
    session_id: str,
    *,
    state_dir: Path,
    timeout_s: float = _VERDICT_LOCK_TIMEOUT_S,
) -> Iterator[bool]:
    """Serialize one verdict's read-modify-write cycle across hook processes."""

    safe_session_id = _safe_session_id(session_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"session_verdict_lock_{safe_session_id}"
    deadline = time.perf_counter() + max(0.001, timeout_s)
    token = f"{os.getpid()}:{time.time_ns()}:{os.urandom(8).hex()}"
    acquired = False
    while not acquired:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > _VERDICT_LOCK_STALE_S
                if stale:
                    path.unlink()
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
            if time.perf_counter() >= deadline:
                append_hook_error(
                    "VERDICT_LOCK_TIMEOUT",
                    safe_session_id,
                    state_dir=state_dir,
                )
                yield False
                return
            time.sleep(0.005)
        except OSError as exc:
            append_hook_error(
                "VERDICT_LOCK_FAILED",
                type(exc).__name__,
                state_dir=state_dir,
            )
            yield False
            return
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            acquired = True
    try:
        yield True
    finally:
        try:
            if path.read_text(encoding="utf-8") == token:
                path.unlink()
        except (FileNotFoundError, OSError, UnicodeError):
            pass


def read_verdict(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_VERDICT_BYTES:
            return None
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != VERDICT_SCHEMA
            or not isinstance(value.get("session_id"), str)
            or not isinstance(value.get("repo"), str)
            or not isinstance(value.get("verdict"), str)
            or value.get("verdict") not in VERDICT_VALUES
        ):
            return None
        handoff = value.get("handoff_draft")
        if (
            not isinstance(handoff, dict)
            or handoff.get("required")
            is not (value["verdict"] not in {"NO-OP", "ARCHIVE-OK"})
        ):
            return None
        return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def write_verdict(payload: dict[str, Any], *, state_dir: Path) -> Path:
    normalized = dict(payload)
    session_id = _safe_session_id(normalized.get("session_id"))
    if normalized.get("schema_version") != VERDICT_SCHEMA:
        raise ValueError("invalid verdict schema")
    verdict = normalized.get("verdict")
    if verdict not in VERDICT_VALUES:
        raise ValueError("invalid verdict value")
    expected_handoff = verdict not in {"NO-OP", "ARCHIVE-OK"}
    if "handoff_draft" not in normalized:
        normalized["handoff_draft"] = {
            "required": expected_handoff,
            "summary": str(normalized.get("reason") or ""),
        }
    handoff = normalized.get("handoff_draft")
    if not isinstance(handoff, dict) or handoff.get("required") is not expected_handoff:
        raise ValueError("invalid handoff requirement")
    encoded = (
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_VERDICT_BYTES:
        raise ValueError("verdict exceeds size bound")
    path = _verdict_path(session_id, state_dir)
    atomic_write_bytes(path, encoded)
    return path


def _pending_verdicts(
    *,
    repo: str,
    current_session_id: str,
    state_dir: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    candidates: list[tuple[float, str, Path, dict[str, Any]]] = []
    try:
        with os.scandir(state_dir) as entries:
            for entry in entries:
                if not (
                    entry.name.startswith("session_verdict_")
                    and entry.name.endswith(".json")
                    and not entry.is_symlink()
                    and entry.is_file(follow_symlinks=False)
                ):
                    continue
                path = Path(entry.path)
                verdict = read_verdict(path)
                if (
                    verdict is None
                    or verdict.get("repo") != repo
                    or verdict.get("session_id") == current_session_id
                    or verdict.get("consumed_at")
                ):
                    continue
                try:
                    modified = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                item = (modified, path.name, path, verdict)
                if len(candidates) < _MAX_PENDING_RESULTS:
                    heapq.heappush(candidates, item)
                elif (modified, path.name) > (candidates[0][0], candidates[0][1]):
                    heapq.heapreplace(candidates, item)
    except OSError:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [(path, verdict) for _, _, path, verdict in candidates]


def surface_pending_verdict(
    *,
    repo: str,
    current_session_id: str,
    state_dir: Path,
    surfaced_at: str,
) -> dict[str, Any] | None:
    pending = _pending_verdicts(
        repo=repo,
        current_session_id=current_session_id,
        state_dir=state_dir,
    )
    if not pending:
        return None
    path, verdict = pending[0]
    session_id = str(verdict["session_id"])
    with _verdict_lock(session_id, state_dir=state_dir) as acquired:
        if not acquired:
            return read_verdict(path)
        current = read_verdict(path)
        if (
            current is None
            or current.get("repo") != repo
            or current.get("session_id") == current_session_id
            or current.get("consumed_at")
        ):
            return None
        if not current.get("surfaced_at"):
            current["surfaced_at"] = surfaced_at
            write_verdict(current, state_dir=state_dir)
        return read_verdict(path)


def pending_verdict(
    *,
    repo: str,
    current_session_id: str,
    state_dir: Path,
) -> dict[str, Any] | None:
    """Return the newest unconsumed verdict without stamping delivery."""

    pending = _pending_verdicts(
        repo=repo,
        current_session_id=current_session_id,
        state_dir=state_dir,
    )
    return dict(pending[0][1]) if pending else None


def consume_pending_verdict(
    *,
    repo: str,
    current_session_id: str,
    state_dir: Path,
    consumed_at: str,
    expected_session_id: str | None = None,
    expected_created_at: str | None = None,
) -> dict[str, Any] | None:
    if expected_session_id is None:
        pending = _pending_verdicts(
            repo=repo,
            current_session_id=current_session_id,
            state_dir=state_dir,
        )
        if not pending:
            return None
        path, verdict = pending[0]
        target_session_id = str(verdict["session_id"])
    else:
        target_session_id = _safe_session_id(expected_session_id)
        path = _verdict_path(target_session_id, state_dir)
        verdict = read_verdict(path)
        if (
            verdict is None
            or verdict.get("repo") != repo
            or verdict.get("session_id") == current_session_id
            or verdict.get("consumed_at")
            or (
                expected_created_at is not None
                and verdict.get("created_at") != expected_created_at
            )
        ):
            return None
    with _verdict_lock(target_session_id, state_dir=state_dir) as acquired:
        if not acquired:
            return None
        current = read_verdict(path)
        if (
            current is None
            or current.get("repo") != repo
            or current.get("session_id") == current_session_id
            or current.get("consumed_at")
            or (
                expected_created_at is not None
                and current.get("created_at") != expected_created_at
            )
        ):
            return None
        current["consumed_at"] = consumed_at
        write_verdict(current, state_dir=state_dir)
        return current


def _open_items(plan: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    checkpoints = plan.get("checkpoints", [])
    if not isinstance(checkpoints, list):
        return ()
    for item in checkpoints:
        if isinstance(item, str) and item.strip():
            result.append(" ".join(item.split())[:160])
        elif isinstance(item, dict):
            status = str(item.get("status", "open")).strip().lower()
            if status in _CLOSED_STATUSES:
                continue
            text = item.get("text") or item.get("title") or item.get("task") or item.get("id")
            if text:
                result.append(" ".join(str(text).split())[:160])
    return tuple(dict.fromkeys(result))


def decide_verdict(plan: dict[str, Any], evidence: SessionEvidence) -> VerdictDecision:
    baseline_dirty = {
        item for item in plan.get("start_dirty_paths", []) if isinstance(item, str)
    }
    current_dirty = set(evidence.dirty_paths)
    transcript_writes = set(evidence.transcript_written_paths)
    attributable_dirty = (current_dirty - baseline_dirty) | (current_dirty & transcript_writes)
    disappeared_baseline = baseline_dirty - current_dirty
    attributable_paths = tuple(
        sorted(set(evidence.committed_paths) | attributable_dirty)
    )
    open_items = _open_items(plan)

    if not evidence.git_ok:
        return VerdictDecision(
            "UNKNOWN",
            "Git evidence was incomplete or timed out.",
            attributable_paths,
            open_items,
        )
    if disappeared_baseline:
        return VerdictDecision(
            "UNKNOWN",
            "Pre-existing dirty paths disappeared, so destructive session activity cannot be excluded.",
            tuple(sorted(set(attributable_paths) | disappeared_baseline)),
            open_items,
        )
    ambiguous_baseline = (
        current_dirty & baseline_dirty if not evidence.transcript_complete else set()
    )
    if ambiguous_baseline:
        return VerdictDecision(
            "UNKNOWN",
            "Transcript was incomplete, so changes to pre-existing dirty files cannot be attributed.",
            tuple(sorted(set(attributable_paths) | ambiguous_baseline)),
            open_items,
        )
    no_work = not evidence.commit_shas and not attributable_paths
    if no_work:
        return VerdictDecision(
            "NO-OP",
            "No commits or file changes were attributable to this session.",
            (),
            open_items,
        )
    if not evidence.commit_shas and attributable_dirty:
        return VerdictDecision(
            "CHECKPOINT",
            "Attributable uncommitted file changes remain.",
            attributable_paths,
            open_items,
        )
    if not evidence.work_reached_trunk:
        return VerdictDecision(
            "CHECKPOINT",
            "Attributable work has not reached origin/main.",
            attributable_paths,
            open_items,
        )
    if attributable_dirty or open_items:
        return VerdictDecision(
            "HANDOFF",
            "Merged work exists, with attributable dirty files or open checkpoints remaining.",
            attributable_paths,
            open_items,
        )
    return VerdictDecision(
        "ARCHIVE-OK",
        "Attributable work reached origin/main with no open session items.",
        attributable_paths,
        (),
    )


def _relative_repo_path(value: object, *, repo_root: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        relative = candidate.resolve(strict=False).relative_to(repo_root.resolve(strict=False))
    except (OSError, ValueError):
        return None
    return relative.as_posix()


def transcript_written_paths(
    transcript_path: Path,
    *,
    repo_root: Path,
) -> tuple[tuple[str, ...], bool]:
    """Extract file paths from write-like tool calls, never transcript content."""

    try:
        if transcript_path.stat().st_size > MAX_TRANSCRIPT_SCAN_BYTES:
            return (), False
        lines = transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return (), False
    complete = True
    paths: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            complete = False
            continue
        if not isinstance(record, dict):
            continue
        if not projection_complete(record):
            complete = False
        for item in project_record(record):
            for raw_path in write_path_candidates(item):
                relative = _relative_repo_path(raw_path, repo_root=repo_root)
                if relative:
                    paths.append(relative)
    return tuple(dict.fromkeys(paths)), complete


def _git(
    args: list[str],
    *,
    repo_root: Path,
    state_dir: Path,
    deadline: float,
    allowed_returncodes: set[int] = frozenset({0}),
) -> subprocess.CompletedProcess[str] | None:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        append_hook_error("LIFECYCLE_GIT_TIMEOUT", "deadline", state_dir=state_dir)
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(0.5, remaining),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        append_hook_error("LIFECYCLE_GIT_FAILED", type(exc).__name__, state_dir=state_dir)
        return None
    if result.returncode not in allowed_returncodes:
        append_hook_error(
            "LIFECYCLE_GIT_FAILED",
            f"exit={result.returncode}",
            state_dir=state_dir,
        )
        return None
    return result


def _literal_pathspec(path: str) -> str:
    """Encode a repository-relative filename as a top-level literal pathspec."""

    return f":(top,literal){path}"


def collect_evidence(
    *,
    registration: RepositoryRegistration,
    plan: dict[str, Any],
    transcript_path: Path,
    state_dir: Path,
    deadline_s: float = SESSION_END_WORK_DEADLINE_S,
) -> SessionEvidence:
    deadline = time.perf_counter() + deadline_s
    root = registration.worktree_root
    status = _git(
        ["status", "--porcelain=v2", "--branch", "--untracked-files=normal", "-z"],
        repo_root=root,
        state_dir=state_dir,
        deadline=deadline,
    )
    if status is None:
        return SessionEvidence(False, "", "unknown", (), (), (), (), False, None)

    branch, head, dirty_paths = parse_git_status_v2_z(status.stdout)

    start_sha = plan.get("start_sha")
    if (
        not isinstance(start_sha, str)
        or len(start_sha) != 40
        or any(character not in "0123456789abcdefABCDEF" for character in start_sha)
    ):
        return SessionEvidence(
            False,
            head,
            branch,
            dirty_paths,
            (),
            (),
            (),
            False,
            None,
        )
    start_ancestor = _git(
        ["merge-base", "--is-ancestor", start_sha, "HEAD"],
        repo_root=root,
        state_dir=state_dir,
        deadline=deadline,
        allowed_returncodes={0, 1},
    )
    if start_ancestor is None or start_ancestor.returncode != 0:
        return SessionEvidence(
            False,
            head,
            branch,
            dirty_paths,
            (),
            (),
            (),
            False,
            None,
        )
    history = _git(
        ["rev-list", f"{start_sha}..HEAD"],
        repo_root=root,
        state_dir=state_dir,
        deadline=deadline,
    )
    path_diff = _git(
        ["diff", "--name-only", "-z", "--no-renames", start_sha, "HEAD"],
        repo_root=root,
        state_dir=state_dir,
        deadline=deadline,
    )
    if history is None or path_diff is None:
        return SessionEvidence(False, head, branch, dirty_paths, (), (), (), False, None)
    commits = tuple(
        line.strip()
        for line in history.stdout.splitlines()
        if len(line.strip()) == 40
    )
    committed_paths = parse_nul_paths(path_diff.stdout)

    ancestor = _git(
        ["merge-base", "--is-ancestor", "HEAD", "origin/main"],
        repo_root=root,
        state_dir=state_dir,
        deadline=deadline,
        allowed_returncodes={0, 1},
    )
    reached_trunk: bool | None = None
    if ancestor is not None:
        reached_trunk = ancestor.returncode == 0
    if reached_trunk is False and commits:
        effect_diff_args = [
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "HEAD",
            "origin/main",
        ]
        if committed_paths:
            effect_diff_args.extend(
                ["--", *(_literal_pathspec(path) for path in committed_paths)]
            )
        effect_diff = _git(
            effect_diff_args,
            repo_root=root,
            state_dir=state_dir,
            deadline=deadline,
        )
        if effect_diff is None:
            reached_trunk = None
        else:
            reached_trunk = not parse_nul_paths(effect_diff.stdout)

    written_paths, transcript_scan_complete = transcript_written_paths(
        transcript_path,
        repo_root=root,
    )
    if not transcript_scan_complete:
        append_hook_error(
            "LIFECYCLE_TRANSCRIPT_INCOMPLETE",
            "scan",
            state_dir=state_dir,
        )
    # The hook contract says the transcript may lag the in-memory
    # conversation. A syntactically complete file therefore cannot prove that
    # the newest write tool call is present. Keep attribution fail-closed when
    # a session began with pre-existing dirt.
    transcript_complete = False
    git_ok = bool(head) and reached_trunk is not None
    return SessionEvidence(
        git_ok=git_ok,
        head=head,
        branch=branch,
        dirty_paths=dirty_paths,
        commit_shas=commits,
        committed_paths=committed_paths,
        transcript_written_paths=written_paths,
        transcript_complete=transcript_complete,
        work_reached_trunk=reached_trunk,
    )


def _run_reaper(
    *,
    state_dir: Path,
    session_id: str,
    now: datetime,
) -> None:
    try:
        from state_reaper import reap_state

        reap_state(
            state_dir=state_dir,
            current_session_id=session_id,
            live_session_ids=set(),
            now=now,
            max_files=200,
            time_budget_s=0.15,
        )
    except Exception as exc:  # noqa: BLE001 - SessionEnd must finish
        append_hook_error("LIFECYCLE_REAP_FAILED", type(exc).__name__, state_dir=state_dir)


def _binding_matches_event(
    binding: dict[str, Any] | None,
    *,
    registration: RepositoryRegistration,
    transcript_path: Path,
) -> bool:
    if binding is None or binding.get("repo") != registration.name:
        return False
    try:
        return (
            Path(binding["worktree_root"]).resolve(strict=False)
            == registration.worktree_root.resolve(strict=False)
            and Path(binding["transcript_path"]).resolve(strict=False)
            == transcript_path.resolve(strict=False)
        )
    except (KeyError, OSError, RuntimeError, TypeError):
        return False


def handle_event(
    event: dict[str, Any],
    *,
    registry_path: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Persist the SessionEnd verdict. SessionEnd stdout is intentionally empty."""

    target_state = Path(state_dir) if state_dir is not None else _default_state_dir()
    current_time = now or datetime.now(UTC)
    try:
        if not isinstance(event, dict) or event.get("hook_event_name") != "SessionEnd":
            raise ValueError("not SessionEnd")
        session_id = _safe_session_id(event.get("session_id"))
        cwd_raw = event.get("cwd")
        transcript_raw = event.get("transcript_path")
        if not isinstance(cwd_raw, str) or not isinstance(transcript_raw, str):
            raise ValueError("missing SessionEnd fields")
        registration = resolve_repository(
            Path(cwd_raw),
            registry_path=registry_path,
            state_dir=target_state,
        )
        if registration is None:
            return None
        scratch = read_session_plan(session_id, state_dir=target_state)
        binding = read_session_binding(session_id, state_dir=target_state)
        transcript_path = Path(transcript_raw)
        effective_plan: dict[str, Any] = {
            "start_sha": "",
            "start_dirty_paths": [],
            "checkpoints": [],
        }
        if scratch is not None:
            effective_plan["checkpoints"] = scratch.get("checkpoints", [])
        binding_valid = _binding_matches_event(
            binding,
            registration=registration,
            transcript_path=transcript_path,
        )
        if binding_valid and binding is not None:
            effective_plan["start_sha"] = binding["start_sha"]
            effective_plan["start_dirty_paths"] = binding["start_dirty_paths"]
            evidence = collect_evidence(
                registration=registration,
                plan=effective_plan,
                transcript_path=Path(binding["transcript_path"]),
                state_dir=target_state,
            )
        else:
            append_hook_error(
                "LIFECYCLE_BINDING_MISMATCH",
                session_id,
                state_dir=target_state,
            )
            evidence = SessionEvidence(
                False,
                "",
                "unknown",
                (),
                (),
                (),
                (),
                False,
                None,
            )
        decision = decide_verdict(effective_plan, evidence)
        created_at = _iso(current_time)
        verdict: dict[str, Any] = {
            "schema_version": VERDICT_SCHEMA,
            "session_id": session_id,
            "repo": registration.name,
            "start_sha": effective_plan.get("start_sha") or None,
            "end_sha": evidence.head or None,
            "branch": evidence.branch,
            "verdict": decision.verdict,
            "reason": decision.reason,
            "attributable_commits": list(evidence.commit_shas),
            "attributable_paths": list(decision.attributable_paths),
            "open_items": list(decision.open_items),
            "context_consumption": None,
            "transcript_complete": evidence.transcript_complete,
            "end_reason": event.get("reason") or "other",
            "created_at": created_at,
            "surfaced_at": None,
            "consumed_at": None,
            "handoff_draft": {
                "required": decision.verdict in {"HANDOFF", "CHECKPOINT", "UNKNOWN"},
                "summary": decision.reason,
            },
        }
        write_verdict(verdict, state_dir=target_state)
        _run_reaper(state_dir=target_state, session_id=session_id, now=current_time)
    except Exception as exc:  # noqa: BLE001 - SessionEnd must fail open
        append_hook_error("LIFECYCLE_FAILED", type(exc).__name__, state_dir=target_state)
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        event = {}
    handle_event(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
