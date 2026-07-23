"""Canonical data model for the TruthDeck evidence control plane."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

SCHEMA_VERSION = "truthdeck.snapshot.v1"
TOOL_VERSION = "1.0.0"


class SnapshotValidationError(ValueError):
    """A snapshot violates the closed TruthDeck v1 contract."""


class FactState(StrEnum):
    OBSERVED = "observed"
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICT = "conflict"


class GateState(StrEnum):
    PASS = "PASS"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Stage(StrEnum):
    PLANNED = "planned"
    IMPLEMENTED = "implemented"
    EXACT_HEAD_REVIEWED = "exact_head_reviewed"
    CI = "ci"
    MERGED = "merged"
    RUNTIME_PROVEN = "runtime_proven"


STAGE_ORDER = tuple(Stage)


class ReasonCode(StrEnum):
    COLLECTOR_TIMEOUT = "COLLECTOR_TIMEOUT"
    COLLECTOR_UNAVAILABLE = "COLLECTOR_UNAVAILABLE"
    COLLECTOR_OUTPUT_LIMIT = "COLLECTOR_OUTPUT_LIMIT"
    COLLECTOR_OUTPUT_INVALID = "COLLECTOR_OUTPUT_INVALID"
    COLLECTOR_INTERNAL_ERROR = "COLLECTOR_INTERNAL_ERROR"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    GIT_HEAD_DRIFT = "GIT_HEAD_DRIFT"
    DIRTY_OPERATOR_CHECKOUT = "DIRTY_OPERATOR_CHECKOUT"
    HANDOFF_HASH_MISMATCH = "HANDOFF_HASH_MISMATCH"
    HANDOFF_BASE_STALE = "HANDOFF_BASE_STALE"
    PR_HEAD_MISMATCH = "PR_HEAD_MISMATCH"
    REVIEW_STALE_HEAD = "REVIEW_STALE_HEAD"
    REVIEW_BLOCKING_FINDINGS = "REVIEW_BLOCKING_FINDINGS"
    CI_STALE_HEAD = "CI_STALE_HEAD"
    CI_REQUIRED_CHECK_FAILED = "CI_REQUIRED_CHECK_FAILED"
    MERGE_NOT_PROVEN = "MERGE_NOT_PROVEN"
    RUNTIME_BUILD_MISMATCH = "RUNTIME_BUILD_MISMATCH"
    RUNTIME_EVIDENCE_STALE = "RUNTIME_EVIDENCE_STALE"
    NO_SAMPLE = "NO_SAMPLE"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_UNKNOWN = "AUTHORIZATION_UNKNOWN"
    BOUNDARY_REFUSAL = "BOUNDARY_REFUSAL"
    REGISTRY_INVALID = "REGISTRY_INVALID"
    SNAPSHOT_INVALID = "SNAPSHOT_INVALID"
    STORAGE_CONFLICT = "STORAGE_CONFLICT"


FACT_KEYS: dict[str, dict[str, Any]] = {
    "plan.parseable": {"type": "bool", "producer": "plan", "freshness": "snapshot"},
    "plan.risk": {"type": "str", "producer": "plan", "freshness": "snapshot"},
    "plan.blocked": {"type": "bool", "producer": "plan", "freshness": "snapshot"},
    "git.head": {"type": "str", "producer": "git", "freshness": "live"},
    "git.base": {"type": "str", "producer": "git", "freshness": "live"},
    "git.clean": {"type": "bool", "producer": "git", "freshness": "live"},
    "git.merged": {"type": "bool", "producer": "git", "freshness": "live"},
    "implementation.head": {"type": "str", "producer": "git", "freshness": "live"},
    "pr.head": {"type": "str", "producer": "github", "freshness": "live"},
    "pr.merged": {"type": "bool", "producer": "github", "freshness": "live"},
    "ci.head": {"type": "str", "producer": "github", "freshness": "live"},
    "ci.passed": {"type": "bool", "producer": "github", "freshness": "live"},
    "review.head": {"type": "str", "producer": "review", "freshness": "artifact"},
    "review.blocking_findings": {"type": "int", "producer": "review", "freshness": "artifact"},
    "handoff.valid": {"type": "bool", "producer": "handoff", "freshness": "artifact"},
    "artifact.valid": {"type": "bool", "producer": "artifact", "freshness": "artifact"},
    "artifact.sha256": {"type": "str", "producer": "artifact", "freshness": "artifact"},
    "runtime.applicable": {"type": "bool", "producer": "profile", "freshness": "policy"},
    "runtime.build": {"type": "str", "producer": "runtime", "freshness": "ttl"},
    "runtime.expected_build": {"type": "str", "producer": "profile", "freshness": "policy"},
    "runtime.ready": {"type": "bool", "producer": "runtime", "freshness": "ttl"},
    "runtime.sample_count": {"type": "int", "producer": "runtime", "freshness": "ttl"},
    "authorization.state": {"type": "str", "producer": "operator", "freshness": "artifact"},
}


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    state: FactState
    source_type: str
    source_locator: str
    observed_at_utc: str
    evidence_sha256: str
    fresh_until_utc: str | None = None
    derivation: tuple[str, ...] = ()
    repo_id: str | None = None


@dataclass(frozen=True)
class CollectorRun:
    collector_id: str
    version: str
    elapsed_ms: int
    exit_status: int | None = None
    timed_out: bool = False
    diagnostics: tuple[str, ...] = ()
    repo_id: str | None = None


@dataclass(frozen=True)
class GateResult:
    stage: Stage
    state: GateState
    reason_codes: tuple[ReasonCode, ...] = ()
    evidence_keys: tuple[str, ...] = ()
    detail: str = ""
    repo_id: str | None = None


@dataclass(frozen=True)
class NextAction:
    action_id: str
    summary: str
    stage: Stage | None = None
    reason_codes: tuple[ReasonCode, ...] = ()
    evidence_keys: tuple[str, ...] = ()
    command_preview: tuple[str, ...] = ()
    authorization: str = "not_required"
    reversible: bool = True
    risk: str = "UNKNOWN"
    forbidden_actions: tuple[str, ...] = (
        "application_repo_writes", "runtime_mutation", "broker_or_order_path", "automatic_execution",
    )


@dataclass(frozen=True)
class Scope:
    repos: tuple[str, ...]
    plan: str | None = None
    pr: int | None = None
    task: str | None = None
    required_stages: tuple[Stage, ...] = STAGE_ORDER


@dataclass(frozen=True)
class Snapshot:
    observed_at_utc: str
    scope: Scope
    tool: Mapping[str, str]
    facts: tuple[Fact, ...]
    conflicts: tuple[str, ...]
    gates: tuple[GateResult, ...]
    next_action: NextAction
    boundaries: tuple[str, ...]
    collector_runs: tuple[CollectorRun, ...]
    source_digest_sha256: str
    snapshot_id: str = ""
    schema_version: str = SCHEMA_VERSION

    def with_content_id(self) -> "Snapshot":
        raw = snapshot_to_dict(self, include_snapshot_id=False)
        raw.pop("observed_at_utc", None)
        for fact in raw["facts"]:
            fact.pop("observed_at_utc", None)
        raw["collector_runs"] = [
            {k: v for k, v in run.items() if k not in {"elapsed_ms"}} for run in raw["collector_runs"]
        ]
        content_id = sha256_json(raw)[:24]
        return dataclasses.replace(self, snapshot_id=content_id)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SnapshotValidationError(f"invalid RFC3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SnapshotValidationError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def canonical_json(value: Any) -> bytes:
    _reject_non_finite(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def snapshot_to_dict(snapshot: Snapshot, *, include_snapshot_id: bool = True) -> dict[str, Any]:
    raw = _primitive(snapshot)
    if not include_snapshot_id:
        raw.pop("snapshot_id", None)
    return raw


def snapshot_from_dict(raw: Mapping[str, Any]) -> Snapshot:
    _require_keys(raw, {"schema_version", "snapshot_id", "observed_at_utc", "scope", "tool", "facts", "conflicts", "gates", "next_action", "boundaries", "collector_runs", "source_digest_sha256"}, "snapshot")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise SnapshotValidationError(f"unsupported schema_version: {raw['schema_version']!r}")
    parse_utc(str(raw["observed_at_utc"]))
    scope_raw = _mapping(raw["scope"], "scope")
    scope = Scope(
        repos=tuple(str(x) for x in scope_raw.get("repos", [])),
        plan=_optional_str(scope_raw.get("plan")),
        pr=int(scope_raw["pr"]) if scope_raw.get("pr") is not None else None,
        task=_optional_str(scope_raw.get("task")),
        required_stages=tuple(Stage(x) for x in scope_raw.get("required_stages", [s.value for s in STAGE_ORDER])),
    )
    facts = tuple(_fact_from_dict(x) for x in _sequence(raw["facts"], "facts"))
    gates = tuple(_gate_from_dict(x) for x in _sequence(raw["gates"], "gates"))
    runs = tuple(_run_from_dict(x) for x in _sequence(raw["collector_runs"], "collector_runs"))
    action_raw = _mapping(raw["next_action"], "next_action")
    action = NextAction(
        action_id=str(action_raw.get("action_id", "")),
        summary=str(action_raw.get("summary", "")),
        stage=Stage(action_raw["stage"]) if action_raw.get("stage") else None,
        reason_codes=tuple(ReasonCode(x) for x in action_raw.get("reason_codes", [])),
        evidence_keys=tuple(str(x) for x in action_raw.get("evidence_keys", [])),
        command_preview=tuple(str(x) for x in action_raw.get("command_preview", [])),
        authorization=str(action_raw.get("authorization", "not_required")),
        reversible=bool(action_raw.get("reversible", True)),
        risk=str(action_raw.get("risk", "UNKNOWN")),
        forbidden_actions=tuple(str(x) for x in action_raw.get("forbidden_actions", [])),
    )
    snapshot = Snapshot(
        schema_version=str(raw["schema_version"]), snapshot_id=str(raw["snapshot_id"]),
        observed_at_utc=str(raw["observed_at_utc"]), scope=scope,
        tool={str(k): str(v) for k, v in _mapping(raw["tool"], "tool").items()},
        facts=facts, conflicts=tuple(str(x) for x in _sequence(raw["conflicts"], "conflicts")),
        gates=gates, next_action=action,
        boundaries=tuple(str(x) for x in _sequence(raw["boundaries"], "boundaries")),
        collector_runs=runs, source_digest_sha256=str(raw["source_digest_sha256"]),
    )
    if snapshot.snapshot_id != snapshot.with_content_id().snapshot_id:
        raise SnapshotValidationError("snapshot_id does not match canonical content")
    return snapshot


def make_fact(key: str, value: Any, *, state: FactState = FactState.OBSERVED,
              source_type: str, source_locator: str, observed_at_utc: str,
              fresh_until_utc: str | None = None, derivation: tuple[str, ...] = (),
              repo_id: str | None = None, evidence: Any | None = None) -> Fact:
    if key not in FACT_KEYS:
        raise SnapshotValidationError(f"unknown fact key: {key}")
    _validate_fact_type(key, value, state)
    parse_utc(observed_at_utc)
    if fresh_until_utc:
        parse_utc(fresh_until_utc)
    return Fact(key, value, state, source_type, source_locator, observed_at_utc,
                sha256_json(value if evidence is None else evidence), fresh_until_utc,
                tuple(derivation), repo_id)


def _fact_from_dict(value: Any) -> Fact:
    raw = _mapping(value, "fact")
    fact = Fact(
        key=str(raw["key"]), value=raw.get("value"), state=FactState(raw["state"]),
        source_type=str(raw["source_type"]), source_locator=str(raw["source_locator"]),
        observed_at_utc=str(raw["observed_at_utc"]), evidence_sha256=str(raw["evidence_sha256"]),
        fresh_until_utc=_optional_str(raw.get("fresh_until_utc")),
        derivation=tuple(str(x) for x in raw.get("derivation", [])), repo_id=_optional_str(raw.get("repo_id")),
    )
    if fact.key not in FACT_KEYS:
        raise SnapshotValidationError(f"unknown fact key: {fact.key}")
    _validate_fact_type(fact.key, fact.value, fact.state)
    parse_utc(fact.observed_at_utc)
    if fact.fresh_until_utc:
        parse_utc(fact.fresh_until_utc)
    return fact


def _gate_from_dict(value: Any) -> GateResult:
    raw = _mapping(value, "gate")
    return GateResult(Stage(raw["stage"]), GateState(raw["state"]),
                      tuple(ReasonCode(x) for x in raw.get("reason_codes", [])),
                      tuple(str(x) for x in raw.get("evidence_keys", [])), str(raw.get("detail", "")),
                      _optional_str(raw.get("repo_id")))


def _run_from_dict(value: Any) -> CollectorRun:
    raw = _mapping(value, "collector_run")
    return CollectorRun(str(raw["collector_id"]), str(raw["version"]), int(raw["elapsed_ms"]),
                        int(raw["exit_status"]) if raw.get("exit_status") is not None else None,
                        bool(raw.get("timed_out", False)), tuple(str(x) for x in raw.get("diagnostics", [])),
                        _optional_str(raw.get("repo_id")))


def _validate_fact_type(key: str, value: Any, state: FactState) -> None:
    if state in {FactState.UNAVAILABLE, FactState.STALE, FactState.CONFLICT} and value is None:
        return
    expected = FACT_KEYS[key]["type"]
    checks = {"bool": lambda x: type(x) is bool, "str": lambda x: isinstance(x, str), "int": lambda x: type(x) is int}
    if not checks[expected](value):
        raise SnapshotValidationError(f"fact {key} expected {expected}, got {type(value).__name__}")


def _primitive(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: _primitive(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(x) for x in value]
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise SnapshotValidationError("non-finite numeric value")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def _require_keys(raw: Mapping[str, Any], keys: set[str], label: str) -> None:
    missing = keys - set(raw)
    unknown = set(raw) - keys
    if missing or unknown:
        raise SnapshotValidationError(f"{label} keys invalid; missing={sorted(missing)} unknown={sorted(unknown)}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SnapshotValidationError(f"{label} must be an array")
    return value


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
