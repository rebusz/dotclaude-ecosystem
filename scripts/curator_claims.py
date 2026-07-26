#!/usr/bin/env python3
"""Build a redacted, fail-closed curator packet for the current session."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Iterable

from session_lifecycle import consume_pending_verdict, pending_verdict
from session_state import (
    append_hook_error,
    atomic_write_bytes,
    parse_nul_paths,
    read_session_binding,
    read_session_plan,
    validate_session_id,
)
from terminal_evidence import redact_text

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


MAX_REDACTED_WINDOW_CHARS = 20_000
MAX_TRANSCRIPT_SOURCE_BYTES = 4 * 1024 * 1024
TRUTH_TIMEOUT_S = 20.0

_CLAIM_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_COMMIT_RE = re.compile(r"\bcommit(?:ted)?(?:\s+as)?\s+([0-9a-fA-F]{7,40})\b", re.I)
_PASS_COUNT_RE = re.compile(r"\b(\d+)\s+(?:tests?\b.{0,120}?\b)?passed\b", re.I)
_ARTIFACT_RE = re.compile(r"`([^`\r\n]{1,240})`")
_CHANGE_RE = re.compile(
    r"\b(fixed|implemented|changed|added|removed|updated|created|deleted)\b",
    re.I,
)
_CI_RE = re.compile(r"\bci\b.*\b(passed|green|succeeded|successful)\b", re.I)
_TEST_RE = re.compile(
    r"\btests?\s+passed\b|\b\d+\s+(?:tests?\b.{0,120}?\b)?passed\b",
    re.I,
)
_SENSITIVE_KEY_RE = re.compile(
    r"^(api[_-]?key|authorization|bearer|cookie|password|passwd|secret|token)$",
    re.I,
)
_BEARER_RE = re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)[^\s,;]+")
_COOKIE_RE = re.compile(r"(?i)\b(cookie|set-cookie)\s*:\s*[^\r\n]+")
_GITHUB_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.S,
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


@dataclass(frozen=True)
class CommandEvidence:
    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class TranscriptWindow:
    redacted_window: str
    assistant_messages: tuple[str, ...]
    command_evidence: tuple[CommandEvidence, ...]
    observed_tail: str | None
    complete: bool
    source_truncated: bool


@dataclass(frozen=True)
class ChangedPathEvidence:
    paths: frozenset[str]
    complete: bool
    baseline_ambiguous_paths: frozenset[str] = frozenset()


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _default_state_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_STATE_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude" / "state"


def redact_structure(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if _SENSITIVE_KEY_RE.fullmatch(str(key))
            else redact_structure(item)
            for key, item in value.items()
        }
    return value


def _redact_projection_text(value: str) -> str:
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", value)
    redacted = _COOKIE_RE.sub(r"\1: [REDACTED]", redacted)
    redacted = _GITHUB_TOKEN_RE.sub("[REDACTED]", redacted)
    redacted = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", redacted)
    redacted = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", redacted)
    return redact_text(redacted)


def _recent_jsonl_lines(path: Path) -> tuple[list[str], bool]:
    size = path.stat().st_size
    truncated = size > MAX_TRANSCRIPT_SOURCE_BYTES
    with path.open("rb") as handle:
        if truncated:
            handle.seek(-MAX_TRANSCRIPT_SOURCE_BYTES, os.SEEK_END)
            handle.readline()
        payload = handle.read(MAX_TRANSCRIPT_SOURCE_BYTES)
    return payload.decode("utf-8", errors="replace").splitlines(), truncated


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _assistant_text(record: dict[str, Any]) -> str:
    if record.get("type") != "assistant":
        return ""
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _structured_tool_result(record: dict[str, Any]) -> tuple[int, str] | None:
    value = record.get("toolUseResult")
    if not isinstance(value, dict):
        value = record.get("tool_use_result")
    if not isinstance(value, dict):
        return None
    exit_code = value.get("exitCode")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = value.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return None
    output = "\n".join(_strings(value))
    return exit_code, output[:8000]


def _tool_use_commands(record: dict[str, Any]) -> dict[str, str]:
    commands: dict[str, str] = {}
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return commands
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_id = block.get("id")
        tool_input = block.get("input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if isinstance(tool_id, str) and isinstance(command, str):
            commands[tool_id] = command[:1000]
    return commands


def _tool_result_ids(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    direct = record.get("tool_use_id") or record.get("toolUseId")
    if isinstance(direct, str):
        result.append(direct)
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id") or block.get("toolUseId")
            if isinstance(tool_id, str):
                result.append(tool_id)
    return list(dict.fromkeys(result))


def _command_evidence_from_records(
    records: Iterable[dict[str, Any]],
) -> tuple[CommandEvidence, ...]:
    commands_by_id: dict[str, str] = {}
    result: list[CommandEvidence] = []
    for record in records:
        commands_by_id.update(_tool_use_commands(record))
        structured = _structured_tool_result(record)
        if structured is None:
            continue
        ids = _tool_result_ids(record)
        matches = [commands_by_id[item] for item in ids if item in commands_by_id]
        if len(matches) != 1:
            continue
        exit_code, output = structured
        result.append(
            CommandEvidence(
                command=matches[0],
                exit_code=exit_code,
                output=output,
            )
        )
    return tuple(result)


def build_transcript_window(path: Path) -> TranscriptWindow:
    lines, source_truncated = _recent_jsonl_lines(path)
    records: list[dict[str, Any]] = []
    projections: deque[tuple[str, str]] = deque()
    total = 0
    parse_complete = True
    observed_tail: str | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            parse_complete = False
            continue
        if not isinstance(raw, dict):
            continue
        records.append(raw)
        timestamp = ""
        for key in ("timestamp", "created_at", "createdAt"):
            candidate = raw.get(key)
            if isinstance(candidate, str) and candidate.strip():
                timestamp = candidate.strip()
                observed_tail = timestamp
                break
        assistant_text = _assistant_text(raw)
        if not assistant_text:
            continue
        safe_text = _redact_projection_text(assistant_text)
        rendered = f"[{timestamp or 'timestamp unknown'}] {safe_text}"
        projections.append((rendered, safe_text))
        total += len(rendered) + 1
        while len(projections) > 1 and total > MAX_REDACTED_WINDOW_CHARS:
            removed, _ = projections.popleft()
            total -= len(removed) + 1

    redacted_window = "\n".join(rendered for rendered, _ in projections)
    if len(redacted_window) > MAX_REDACTED_WINDOW_CHARS:
        redacted_window = redacted_window[-MAX_REDACTED_WINDOW_CHARS:]
    return TranscriptWindow(
        redacted_window=redacted_window,
        assistant_messages=tuple(text for _, text in projections),
        command_evidence=_command_evidence_from_records(records),
        observed_tail=observed_tail,
        # The official hook contract says the transcript may lag the in-memory
        # turn, so the curator never claims complete conversational coverage.
        complete=False,
        source_truncated=source_truncated or not parse_complete,
    )


def extract_claims(messages: Iterable[str]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        for sentence in _CLAIM_SPLIT_RE.split(message):
            text = " ".join(sentence.split()).strip()
            if not text or text in seen:
                continue
            commit = _COMMIT_RE.search(text)
            pass_count = _PASS_COUNT_RE.search(text)
            evidence_classes: list[str] = []
            if commit:
                kind = "commit"
            elif _CI_RE.search(text):
                kind = "ci"
            elif _TEST_RE.search(text):
                kind = "test"
            elif _CHANGE_RE.search(text):
                kind = "change"
            else:
                continue
            if commit:
                evidence_classes.append("commit")
            if _CI_RE.search(text):
                evidence_classes.append("ci")
            if _TEST_RE.search(text):
                evidence_classes.append("test")
            if _CHANGE_RE.search(text):
                evidence_classes.append("change")
            artifacts = [
                value.replace("\\", "/")
                for value in _ARTIFACT_RE.findall(text)
                if "/" in value or "\\" in value or "." in Path(value).name
            ]
            claims.append(
                {
                    "text": text[:500],
                    "kind": kind,
                    "evidence_classes": evidence_classes,
                    "requires_change_evidence": bool(_CHANGE_RE.search(text)),
                    "test_scope_artifacts": (
                        artifacts
                        if "test" in evidence_classes and "change" not in evidence_classes
                        else []
                    ),
                    "commit": commit.group(1) if commit else None,
                    "artifacts": artifacts[:10],
                    "expected_pass_count": int(pass_count.group(1)) if pass_count else None,
                }
            )
            seen.add(text)
    return claims


def _result(claim: dict[str, Any], state: str, reason: str) -> dict[str, Any]:
    return {
        "claim": claim["text"],
        "kind": claim["kind"],
        "state": state,
        "reason": reason,
        "artifacts": claim.get("artifacts", []),
    }


def _session_commit_shas(repo_root: Path, start_sha: str) -> set[str] | None:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", start_sha):
        return None
    try:
        ancestor = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", start_sha, "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
        if ancestor.returncode != 0:
            return None
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", f"{start_sha}..HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        return {
            line.strip().lower()
            for line in result.stdout.splitlines()
            if re.fullmatch(r"[0-9a-fA-F]{40}", line.strip())
        }
    except (OSError, subprocess.TimeoutExpired):
        return None


def _match_artifacts(
    artifacts: Iterable[str],
    *,
    changed_paths: set[str],
    repo_root: Path,
) -> tuple[set[str], bool, bool]:
    normalized_changes = {
        normalized
        for item in changed_paths
        if (normalized := _normalize_relative_artifact(item)) is not None
    }
    matches: set[str] = set()
    ambiguous = False
    artifact_values = list(dict.fromkeys(artifacts))
    matched_artifacts = 0
    for raw in artifact_values:
        value = re.sub(r":\d+(?::\d+)?$", "", raw.strip()).replace("\\", "/")
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                value = candidate.resolve(strict=False).relative_to(
                    repo_root.resolve(strict=False)
                ).as_posix()
            except (OSError, ValueError):
                continue
        normalized_value = _normalize_relative_artifact(value)
        if normalized_value is None:
            continue
        value = normalized_value
        if value in normalized_changes:
            matches.add(value)
            matched_artifacts += 1
            continue
        if "/" not in value:
            suffix_matches = {
                item for item in normalized_changes if PurePath(item).name == value
            }
            if len(suffix_matches) == 1:
                matches.update(suffix_matches)
                matched_artifacts += 1
            elif len(suffix_matches) > 1:
                ambiguous = True
    return matches, ambiguous, matched_artifacts == len(artifact_values)


def _gate_state(snapshot: dict[str, Any], stage: str) -> str | None:
    gates = snapshot.get("gates")
    if not isinstance(gates, list):
        return None
    for gate in gates:
        if isinstance(gate, dict) and gate.get("stage") == stage:
            value = gate.get("state")
            return value if isinstance(value, str) else None
    return None


def verify_claims(
    claims: Iterable[dict[str, Any]],
    *,
    repo_root: Path,
    start_sha: str,
    changed_paths: set[str] | ChangedPathEvidence,
    command_evidence: tuple[CommandEvidence, ...],
    truth_snapshot: dict[str, Any] | None,
    truth_fresh: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(changed_paths, ChangedPathEvidence):
        changed_path_values = set(changed_paths.paths)
        changed_paths_complete = changed_paths.complete
        baseline_ambiguous_values = set(changed_paths.baseline_ambiguous_paths)
    else:
        changed_path_values = changed_paths
        changed_paths_complete = True
        baseline_ambiguous_values = set()
    session_commits = (
        _session_commit_shas(repo_root, start_sha)
        if truth_snapshot is not None and truth_fresh
        else None
    )
    for claim in claims:
        if truth_snapshot is None or not truth_fresh:
            results.append(
                _result(
                    claim,
                    "UNVERIFIED",
                    "Fresh TruthDeck evidence was unavailable or did not match current HEAD.",
                )
            )
            continue
        kind = claim["kind"]
        evidence_classes = claim.get("evidence_classes")
        if not isinstance(evidence_classes, list):
            evidence_classes = [kind]
        classes = tuple(
            dict.fromkeys(
                item
                for item in evidence_classes
                if item in {"commit", "ci", "test", "change"}
            )
        )
        if len(classes) > 1:
            facet_results: list[dict[str, Any]] = []
            for evidence_class in classes:
                facet = dict(claim)
                facet["kind"] = evidence_class
                facet["evidence_classes"] = [evidence_class]
                facet["requires_change_evidence"] = evidence_class == "change"
                facet_results.extend(
                    verify_claims(
                        [facet],
                        repo_root=repo_root,
                        start_sha=start_sha,
                        changed_paths=changed_paths,
                        command_evidence=command_evidence,
                        truth_snapshot=truth_snapshot,
                        truth_fresh=truth_fresh,
                    )
                )
            states = {item["state"] for item in facet_results}
            combined_state = (
                "REFUTED"
                if "REFUTED" in states
                else "VERIFIED"
                if states == {"VERIFIED"}
                else "UNVERIFIED"
            )
            combined_reason = "; ".join(
                f"{item['kind']}: {item['state']} ({item['reason']})"
                for item in facet_results
            )
            results.append(_result(claim, combined_state, combined_reason))
            continue
        if claim.get("requires_change_evidence"):
            artifacts = {
                str(item).replace("\\", "/")
                for item in claim.get("artifacts", [])
                if isinstance(item, str)
            }
            if not artifacts:
                results.append(
                    _result(
                        claim,
                        "UNVERIFIED",
                        "The change portion names no concrete file artifact.",
                    )
                )
                continue
            matched, ambiguous, all_matched = _match_artifacts(
                artifacts,
                changed_paths=changed_path_values,
                repo_root=repo_root,
            )
            if ambiguous:
                results.append(
                    _result(claim, "UNVERIFIED", "A named artifact matched multiple changed files.")
                )
                continue
            if not all_matched:
                attributable_or_baseline = changed_path_values | baseline_ambiguous_values
                combined_matched, combined_ambiguous, combined_all_matched = _match_artifacts(
                    artifacts,
                    changed_paths=attributable_or_baseline,
                    repo_root=repo_root,
                )
                if combined_ambiguous:
                    results.append(
                        _result(
                            claim,
                            "UNVERIFIED",
                            "A named artifact matched multiple changed or baseline-dirty files.",
                        )
                    )
                    continue
                if combined_all_matched and combined_matched - matched:
                    results.append(
                        _result(
                            claim,
                            "UNVERIFIED",
                            "One or more named artifacts were dirty at session start and lack "
                            "session-attributable change evidence.",
                        )
                    )
                    continue
                if not changed_paths_complete:
                    results.append(
                        _result(
                            claim,
                            "UNVERIFIED",
                            "Git path evidence was incomplete, so absence cannot refute the claim.",
                        )
                    )
                else:
                    results.append(
                        _result(
                            claim,
                            "REFUTED",
                            "One or more named artifacts are absent from session changes.",
                        )
                    )
                continue
            if kind == "change":
                results.append(
                    _result(claim, "VERIFIED", "Changed artifact: " + ", ".join(sorted(matched)))
                )
                continue
        if kind == "commit":
            sha = claim.get("commit")
            matches = (
                {
                    candidate
                    for candidate in session_commits
                    if isinstance(sha, str) and candidate.startswith(sha.lower())
                }
                if session_commits is not None
                else set()
            )
            if len(matches) == 1:
                results.append(
                    _result(claim, "VERIFIED", f"Commit {sha} is attributable to this session.")
                )
            elif session_commits is None:
                results.append(
                    _result(claim, "UNVERIFIED", "The session commit range was unavailable.")
                )
            elif isinstance(sha, str) and not matches:
                results.append(
                    _result(claim, "REFUTED", f"Commit {sha} is outside this session's range.")
                )
            elif len(matches) > 1:
                results.append(
                    _result(claim, "UNVERIFIED", f"Commit prefix {sha} is ambiguous.")
                )
            else:
                results.append(_result(claim, "UNVERIFIED", "No commit SHA was stated."))
        elif kind == "change":
            results.append(_result(claim, "UNVERIFIED", "No change evidence was available."))
        elif kind == "test":
            expected = claim.get("expected_pass_count")
            relevant = [
                item
                for item in command_evidence
                if _is_test_command(item.command)
            ]
            latest = relevant[-1] if relevant else None
            test_scope_artifacts = [
                item
                for item in claim.get("test_scope_artifacts", [])
                if isinstance(item, str)
            ]
            if (
                latest is not None
                and test_scope_artifacts
                and not _test_command_covers_artifacts(
                    latest.command,
                    test_scope_artifacts,
                    repo_root=repo_root,
                )
            ):
                results.append(
                    _result(
                        claim,
                        "UNVERIFIED",
                        "The test command scope does not cover every named test artifact.",
                    )
                )
                continue
            observed_count = _test_pass_count(latest.output) if latest is not None else None
            expected_output = (
                observed_count == expected
                if expected is not None
                else observed_count is not None and observed_count > 0
            )
            if latest is not None and latest.exit_code == 0 and expected_output:
                results.append(
                    _result(claim, "VERIFIED", "The latest matching test command exited 0.")
                )
            elif latest is not None and latest.exit_code not in {None, 0}:
                results.append(_result(claim, "REFUTED", "Recorded test command failed."))
            else:
                results.append(
                    _result(claim, "UNVERIFIED", "No matching test exit evidence was recorded.")
                )
        elif kind == "ci":
            state = _gate_state(truth_snapshot, "ci")
            if state == "PASS":
                results.append(_result(claim, "VERIFIED", "Fresh TruthDeck CI gate is PASS."))
            elif state in {"HOLD", "BLOCKED"}:
                results.append(
                    _result(claim, "REFUTED", f"Fresh TruthDeck CI gate is {state}.")
                )
            else:
                results.append(_result(claim, "UNVERIFIED", "Fresh CI gate is not decisive."))
        else:
            results.append(_result(claim, "UNVERIFIED", "Unsupported claim type."))
    return results


def run_truth_snapshot(
    repo_root: Path,
    *,
    truthctl_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    script = truthctl_path or Path(__file__).with_name("truthctl.py")
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "snapshot",
                "--repo",
                str(repo_root),
                "--no-store",
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TRUTH_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return None, "truthctl unavailable"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    if result.returncode not in {0, 12}:
        return None, f"truthctl failed (exit {result.returncode})"
    try:
        snapshot = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, f"truthctl returned invalid JSON (exit {result.returncode})"
    if not isinstance(snapshot, dict):
        return None, "truthctl returned a non-object snapshot"
    return snapshot, None


def current_head(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def current_git_root(repo_root: Path) -> Path | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--show-toplevel",
                "--path-format=absolute",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return Path(result.stdout.strip()).resolve(strict=False)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None


def _snapshot_head(snapshot: dict[str, Any] | None) -> str | None:
    if snapshot is None:
        return None
    facts = snapshot.get("facts")
    if not isinstance(facts, list):
        return None
    for key in ("implementation.head", "git.head"):
        for fact in facts:
            if (
                isinstance(fact, dict)
                and fact.get("key") == key
                and fact.get("state") in {"observed", "derived"}
                and isinstance(fact.get("value"), str)
            ):
                return fact["value"]
    return None


def _is_test_command(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    if re.search(r"[;&|\r\n]", command):
        return False
    patterns = (
        r"(?:^|[;&|]\s*)(?:python(?:\.exe)?\s+-m\s+)?pytest(?:\s|$)",
        r"(?:^|[;&|]\s*)(?:python(?:\.exe)?\s+-m\s+)?unittest(?:\s|$)",
        r"(?:^|[;&|]\s*)(?:npm|pnpm|yarn|bun)(?:\s+run)?\s+test(?:\s|$)",
        r"(?:^|[;&|]\s*)cargo\s+test(?:\s|$)",
        r"(?:^|[;&|]\s*)go\s+test(?:\s|$)",
        r"(?:^|[;&|]\s*)dotnet\s+test(?:\s|$)",
    )
    return any(re.search(pattern, normalized, re.I) for pattern in patterns)


def _test_pass_count(output: str) -> int | None:
    pytest_counts = [
        int(match)
        for match in re.findall(r"\b(\d+)\s+passed\b", output, re.I)
    ]
    if pytest_counts:
        return pytest_counts[-1]
    unittest_matches = re.findall(r"\bRan\s+(\d+)\s+tests?\b", output, re.I)
    if unittest_matches and re.search(r"(?m)^OK(?:\s|$)", output):
        return int(unittest_matches[-1])
    return None


def _normalize_relative_artifact(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _test_command_covers_artifacts(
    command: str,
    artifacts: Iterable[str],
    *,
    repo_root: Path,
) -> bool:
    try:
        tokens = [
            token.strip("\"'").replace("\\", "/")
            for token in shlex.split(command, posix=False)
        ]
    except ValueError:
        return False
    targets: list[str] = []
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
            continue
        lowered = token.lower()
        if lowered in {
            "-k",
            "-m",
            "--basetemp",
            "--rootdir",
            "--confcutdir",
            "--ignore",
            "--deselect",
        }:
            skip_value = True
            continue
        if token.startswith("-"):
            continue
        raw_target = token.split("::", 1)[0].rstrip("/")
        if (
            "/" in raw_target
            or re.search(r"\.(?:py|js|jsx|ts|tsx|rs|go|cs)$", raw_target, re.I)
            or PurePath(raw_target).name.lower() in {"test", "tests"}
        ):
            candidate = Path(raw_target)
            if candidate.is_absolute():
                try:
                    target = candidate.resolve(strict=False).relative_to(
                        repo_root.resolve(strict=False)
                    ).as_posix()
                except (OSError, ValueError):
                    continue
            else:
                target = _normalize_relative_artifact(raw_target)
                if target is None:
                    continue
            targets.append(target)
    if not targets:
        return False
    for raw in artifacts:
        raw_artifact = re.sub(r":\d+(?::\d+)?$", "", raw.strip())
        artifact = _normalize_relative_artifact(raw_artifact)
        if artifact is None:
            return False
        basename_only = "/" not in artifact
        if not any(
            artifact == target
            or artifact.startswith(target.rstrip("/") + "/")
            or (basename_only and artifact == PurePath(target).name)
            for target in targets
        ):
            return False
    return True


def changed_paths(
    repo_root: Path,
    start_sha: str,
    start_dirty_paths: Iterable[str] = (),
) -> ChangedPathEvidence:
    committed_paths: set[str] = set()
    working_paths: set[str] = set()
    complete = bool(re.fullmatch(r"[0-9a-fA-F]{40}", start_sha))
    if not complete:
        return ChangedPathEvidence(frozenset(), False)
    baseline_dirty = {
        item for item in start_dirty_paths if isinstance(item, str)
    }
    commands = [
        ["diff", "--name-only", "-z", "--no-renames", f"{start_sha}..HEAD"],
        ["diff", "--name-only", "-z", "--no-renames", "HEAD"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ]
    for index, args in enumerate(commands):
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            complete = False
            continue
        if result.returncode != 0:
            complete = False
            continue
        parsed = set(parse_nul_paths(result.stdout))
        if index == 0:
            committed_paths.update(parsed)
        else:
            working_paths.update(parsed)
    baseline_ambiguous = baseline_dirty - committed_paths
    attributable_paths = committed_paths | (working_paths - baseline_dirty)
    return ChangedPathEvidence(
        frozenset(attributable_paths),
        complete,
        frozenset(baseline_ambiguous),
    )


def _render_gates(snapshot: dict[str, Any] | None, *, fresh: bool) -> list[dict[str, Any]]:
    if snapshot is None or not isinstance(snapshot.get("gates"), list):
        return []
    rendered: list[dict[str, Any]] = []
    for gate in snapshot["gates"]:
        if not isinstance(gate, dict):
            continue
        state = gate.get("state")
        rendered.append(
            {
                "stage": gate.get("stage"),
                "state": state if fresh else "UNVERIFIED",
                "source_state": state,
                "reason_codes": gate.get("reason_codes", []),
            }
        )
    return rendered


def _write_handoff(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Curator verified-close handoff",
        "",
        f"- Session: `{report['session_id']}`",
        f"- Router scratch evidence: `{str(report['router_evidence']).lower()}`",
        f"- Transcript status: `{report['transcript']['status']}`",
        f"- Transcript observed tail: `{report['transcript']['observed_tail'] or 'unknown'}`",
        "- Transcript coverage: incomplete by contract; the file may lag the current turn.",
        f"- TruthDeck: `{report['truth']['status']}`",
        "",
        "## Claims",
        "",
    ]
    claims = report["claims"]
    if not claims:
        lines.append("- No concrete claims were present in the observed transcript tail.")
    else:
        for claim in claims:
            lines.append(
                f"- **{claim['state']}** — {claim['claim']} — {claim['reason']}"
            )
    lines.extend(["", "## Previous SessionEnd verdict", ""])
    previous = report.get("previous_verdict")
    if previous:
        lines.append(
            f"- `{previous.get('verdict', 'UNKNOWN')}` — "
            f"{previous.get('reason', 'no reason recorded')}"
        )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Suggested skills",
            "",
            "- `executor` for remaining implementation.",
            "- `review` for exact-head verification.",
            "- `/hooks` for the authoritative merged hook configuration.",
            "",
        ]
    )
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


def prepare_curator_report(
    *,
    session_id: str,
    repo_root: Path,
    state_dir: Path | None = None,
    now: datetime | None = None,
    output_path: Path | None = None,
    run_truth: bool = True,
) -> dict[str, Any]:
    target_state = Path(state_dir) if state_dir is not None else _default_state_dir()
    current_time = now or datetime.now(UTC)
    session_id = validate_session_id(session_id)
    plan = read_session_plan(session_id, state_dir=target_state)
    binding = read_session_binding(session_id, state_dir=target_state)
    requested_root = repo_root.resolve(strict=False)
    observed_root = current_git_root(requested_root)
    try:
        bound_root = (
            Path(binding["worktree_root"]).resolve(strict=False)
            if binding is not None
            else None
        )
    except (KeyError, OSError, RuntimeError, TypeError):
        bound_root = None
    try:
        requested_within_root = (
            observed_root is not None
            and requested_root.relative_to(observed_root) is not None
        )
    except ValueError:
        requested_within_root = False
    binding_valid = bool(
        binding is not None
        and observed_root is not None
        and bound_root == observed_root
        and requested_within_root
    )
    router_evidence = plan is not None and binding_valid

    truth_snapshot: dict[str, Any] | None = None
    truth_error: str | None = (
        "disabled" if binding_valid else "session binding unavailable or mismatched"
    )
    if run_truth and binding_valid:
        truth_snapshot, truth_error = run_truth_snapshot(observed_root)
    head = current_head(observed_root) if truth_snapshot is not None and observed_root else None
    snapshot_head = _snapshot_head(truth_snapshot)
    truth_fresh = bool(head and snapshot_head and head == snapshot_head)

    window: TranscriptWindow | None = None
    transcript_status = "missing_binding"
    claims: list[dict[str, Any]]
    transcript_path = binding.get("transcript_path") if binding_valid and binding else None
    if not isinstance(transcript_path, str) or not transcript_path:
        append_hook_error(
            "CURATOR_TRANSCRIPT_MISSING",
            "binding",
            state_dir=target_state,
        )
        claims = [
            {
                "claim": "Session transcript was unavailable.",
                "kind": "coverage",
                "state": "UNVERIFIED",
                "reason": "Exact session transcript binding is unavailable or mismatched.",
                "artifacts": [],
            }
        ]
    else:
        try:
            window = build_transcript_window(Path(transcript_path))
            transcript_status = "observed"
        except OSError as exc:
            transcript_status = "unreadable"
            append_hook_error(
                "CURATOR_TRANSCRIPT_MISSING",
                type(exc).__name__,
                state_dir=target_state,
            )
        if window is None:
            claims = [
                {
                    "claim": "Session transcript was unavailable.",
                    "kind": "coverage",
                    "state": "UNVERIFIED",
                    "reason": "The bound transcript path is unreadable.",
                    "artifacts": [],
                }
            ]
        else:
            extracted = extract_claims(window.assistant_messages)
            start_sha = str(binding.get("start_sha") or "") if binding else ""
            paths = (
                changed_paths(
                    observed_root,
                    start_sha,
                    binding.get("start_dirty_paths", []) if binding else (),
                )
                if start_sha
                else ChangedPathEvidence(frozenset(), False)
            )
            claims = verify_claims(
                extracted,
                repo_root=observed_root,
                start_sha=start_sha,
                changed_paths=paths,
                command_evidence=window.command_evidence,
                truth_snapshot=truth_snapshot,
                truth_fresh=truth_fresh,
            )

    repo_name = str(binding.get("repo")) if binding_valid and binding else requested_root.name
    previous = (
        pending_verdict(
            repo=repo_name,
            current_session_id=session_id,
            state_dir=target_state,
        )
        if binding_valid
        else None
    )
    report: dict[str, Any] = {
        "schema_version": "curator.report.v1",
        "session_id": session_id,
        "router_evidence": router_evidence,
        "binding_evidence": binding_valid,
        "transcript": {
            "status": transcript_status,
            "observed_tail": window.observed_tail if window else None,
            "complete": False,
            "source_truncated": window.source_truncated if window else False,
        },
        "redacted_window": window.redacted_window if window else "",
        "truth": {
            "status": (
                "fresh"
                if truth_fresh
                else "stale"
                if truth_snapshot is not None
                else "unavailable"
            ),
            "error": truth_error,
            "current_head": head,
            "snapshot_head": snapshot_head,
            "gates": _render_gates(truth_snapshot, fresh=truth_fresh),
        },
        "claims": claims,
        "previous_verdict": previous,
        "hook_configuration": {
            "router_seen": router_evidence,
            "authoritative_check": "/hooks",
        },
    }
    target_output = output_path or (
        Path(tempfile.gettempdir())
        / (
            f"curator-{session_id}-{current_time.strftime('%Y%m%dT%H%M%S')}-"
            f"{secrets.token_hex(4)}.md"
        )
    )
    _write_handoff(target_output, report)
    consumed = None
    if previous is not None:
        previous_session_id = previous.get("session_id")
        previous_created_at = previous.get("created_at")
        if isinstance(previous_session_id, str):
            consumed = consume_pending_verdict(
                repo=repo_name,
                current_session_id=session_id,
                state_dir=target_state,
                consumed_at=_iso(current_time),
                expected_session_id=previous_session_id,
                expected_created_at=(
                    previous_created_at if isinstance(previous_created_at, str) else None
                ),
            )
    if consumed is not None:
        report["previous_verdict"] = consumed
    report["handoff_path"] = str(target_output)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a fail-closed curator packet")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = prepare_curator_report(
            session_id=args.session_id,
            repo_root=args.repo.resolve(strict=False),
            state_dir=args.state_dir,
            output_path=args.output,
        )
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    except Exception as exc:  # noqa: BLE001 - explicit skill degrades to a packet
        print(
            json.dumps(
                {
                    "schema_version": "curator.report.v1",
                    "session_id": args.session_id,
                    "claims": [
                        {
                            "claim": "Curator execution failed.",
                            "state": "UNVERIFIED",
                            "reason": type(exc).__name__,
                        }
                    ],
                },
                separators=(",", ":"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
