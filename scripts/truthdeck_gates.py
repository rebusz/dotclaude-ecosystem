"""Deterministic, fail-closed TruthDeck stage evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from truthdeck_model import Fact, FactState, GateResult, GateState, NextAction, ReasonCode, STAGE_ORDER, Stage, parse_utc


def evaluate(facts: Iterable[Fact], *, required: Iterable[Stage] = STAGE_ORDER,
             evaluated_at: datetime | None = None, boundary_violation: bool = False) -> tuple[tuple[GateResult, ...], NextAction]:
    fact_list = tuple(facts)
    repos = sorted({f.repo_id for f in fact_list if f.repo_id}) or [None]
    required_set = set(required)
    gates: list[GateResult] = []
    for repo in repos:
        index = {f.key: _freshen(f, evaluated_at) for f in fact_list if f.repo_id in {repo, None}}
        gates.extend(_repo_gates(index, repo))
    gates.sort(key=lambda g: ((g.repo_id or ""), STAGE_ORDER.index(g.stage)))
    risk = next((str(f.value) for f in fact_list if f.key == "plan.risk" and _eligible(f)), "UNKNOWN")
    action = select_next_action(gates, required_set, boundary_violation=boundary_violation, risk=risk)
    return tuple(gates), action


def select_next_action(gates: Iterable[GateResult], required: set[Stage], *,
                       boundary_violation: bool = False, risk: str = "UNKNOWN") -> NextAction:
    if boundary_violation:
        return NextAction("boundary_refusal", "Stop: request exceeds a declared read-only boundary.",
                          reason_codes=(ReasonCode.BOUNDARY_REFUSAL,), authorization="operator_required", risk=risk)
    candidates = [g for g in gates if g.stage in required]
    rank = {GateState.BLOCKED: 0, GateState.UNKNOWN: 1, GateState.HOLD: 2}
    pending = [g for g in candidates if g.state in rank]
    if not pending:
        return NextAction("ready_for_operator_review", "All requested evidence gates pass or are explicitly not applicable.", risk=risk)
    pending.sort(key=lambda g: (rank[g.state], STAGE_ORDER.index(g.stage), g.repo_id or ""))
    gate = pending[0]
    return NextAction(
        f"verify_{gate.stage.value}",
        gate.detail or f"Provide fresh evidence for {gate.stage.value}.",
        gate.stage, gate.reason_codes, gate.evidence_keys,
        authorization="operator_required" if ReasonCode.AUTHORIZATION_REQUIRED in gate.reason_codes else "not_required",
        risk=risk,
    )


def overall_state(gates: Iterable[GateResult], required: Iterable[Stage]) -> GateState:
    relevant = [g.state for g in gates if g.stage in set(required)]
    for state in (GateState.BLOCKED, GateState.UNKNOWN, GateState.HOLD):
        if state in relevant:
            return state
    return GateState.PASS


def _repo_gates(f: dict[str, Fact], repo: str | None) -> list[GateResult]:
    return [
        _planned(f, repo), _implemented(f, repo), _reviewed(f, repo),
        _ci(f, repo), _merged(f, repo), _runtime(f, repo),
    ]


def _planned(f: dict[str, Fact], repo: str | None) -> GateResult:
    required = ("plan.parseable", "plan.risk", "plan.blocked")
    missing = _missing(f, required)
    if missing:
        return _unknown(Stage.PLANNED, missing, repo, f)
    if bool(f["plan.blocked"].value):
        return GateResult(Stage.PLANNED, GateState.BLOCKED, evidence_keys=required, detail="Canonical plan is blocked.", repo_id=repo)
    if f["plan.risk"].value in {"R2", "R3"}:
        authorization = f.get("authorization.state")
        if not _eligible(authorization) or authorization.value != "VERIFIED":
            reason = ReasonCode.AUTHORIZATION_UNKNOWN if _eligible(authorization) else ReasonCode.AUTHORIZATION_REQUIRED
            return GateResult(Stage.PLANNED, GateState.HOLD, (reason,), required + ("authorization.state",),
                              "Independent operator authorization is required; v1 cannot self-verify it.", repo)
    return GateResult(Stage.PLANNED, GateState.PASS, evidence_keys=required, repo_id=repo)


def _implemented(f: dict[str, Fact], repo: str | None) -> GateResult:
    fact = f.get("implementation.head") or f.get("git.head")
    if not _eligible(fact):
        return _unknown(Stage.IMPLEMENTED, ("implementation.head",), repo, f)
    clean = f.get("git.clean")
    if _eligible(clean) and not clean.value:
        return GateResult(Stage.IMPLEMENTED, GateState.BLOCKED, (ReasonCode.DIRTY_OPERATOR_CHECKOUT,),
                          (fact.key, clean.key), "Working tree changes are not captured by the implementation head.", repo)
    return GateResult(Stage.IMPLEMENTED, GateState.PASS, evidence_keys=(fact.key,), repo_id=repo)


def _reviewed(f: dict[str, Fact], repo: str | None) -> GateResult:
    head = f.get("implementation.head") or f.get("pr.head") or f.get("git.head")
    review = f.get("review.head")
    blockers = f.get("review.blocking_findings")
    if not all(_eligible(x) for x in (head, review, blockers)):
        return _unknown(Stage.EXACT_HEAD_REVIEWED, ("review.head", "review.blocking_findings"), repo, f)
    if review.value != head.value:
        return GateResult(Stage.EXACT_HEAD_REVIEWED, GateState.BLOCKED, (ReasonCode.REVIEW_STALE_HEAD,),
                          (head.key, review.key), "Review attestation is for a different head.", repo)
    if blockers.value:
        return GateResult(Stage.EXACT_HEAD_REVIEWED, GateState.BLOCKED, (ReasonCode.REVIEW_BLOCKING_FINDINGS,),
                          (blockers.key,), "Ship-blocking review findings remain.", repo)
    return GateResult(Stage.EXACT_HEAD_REVIEWED, GateState.PASS, evidence_keys=(head.key, review.key, blockers.key), repo_id=repo)


def _ci(f: dict[str, Fact], repo: str | None) -> GateResult:
    passed, ci_head = f.get("ci.passed"), f.get("ci.head")
    head = f.get("implementation.head") or f.get("pr.head") or f.get("git.head")
    if not all(_eligible(x) for x in (passed, ci_head, head)):
        return _unknown(Stage.CI, ("ci.passed", "ci.head"), repo, f)
    if ci_head.value != head.value:
        return GateResult(Stage.CI, GateState.BLOCKED, (ReasonCode.CI_STALE_HEAD,), (ci_head.key, head.key), "CI is stale for the implementation head.", repo)
    if not passed.value:
        return GateResult(Stage.CI, GateState.BLOCKED, (ReasonCode.CI_REQUIRED_CHECK_FAILED,), (passed.key,), "A required CI check failed.", repo)
    return GateResult(Stage.CI, GateState.PASS, evidence_keys=(passed.key, ci_head.key), repo_id=repo)


def _merged(f: dict[str, Fact], repo: str | None) -> GateResult:
    fact = f.get("pr.merged") or f.get("git.merged")
    if not _eligible(fact):
        return _unknown(Stage.MERGED, ("pr.merged", "git.merged"), repo, f)
    if not fact.value:
        return GateResult(Stage.MERGED, GateState.HOLD, (ReasonCode.MERGE_NOT_PROVEN,), (fact.key,), "Merge is not proven on the declared base.", repo)
    return GateResult(Stage.MERGED, GateState.PASS, evidence_keys=(fact.key,), repo_id=repo)


def _runtime(f: dict[str, Fact], repo: str | None) -> GateResult:
    applicable = f.get("runtime.applicable")
    if _eligible(applicable) and applicable.value is False:
        return GateResult(Stage.RUNTIME_PROVEN, GateState.NOT_APPLICABLE, evidence_keys=(applicable.key,), repo_id=repo)
    ready, sample = f.get("runtime.ready"), f.get("runtime.sample_count")
    if not all(_eligible(x) for x in (applicable, ready, sample)):
        return _unknown(Stage.RUNTIME_PROVEN, ("runtime.ready", "runtime.sample_count"), repo, f)
    if sample.value <= 0:
        return GateResult(Stage.RUNTIME_PROVEN, GateState.UNKNOWN, (ReasonCode.NO_SAMPLE,), (sample.key,), "Runtime evidence contains no sample.", repo)
    expected, actual = f.get("runtime.expected_build"), f.get("runtime.build")
    if _eligible(expected) and (not _eligible(actual) or expected.value != actual.value):
        return GateResult(Stage.RUNTIME_PROVEN, GateState.BLOCKED, (ReasonCode.RUNTIME_BUILD_MISMATCH,),
                          (expected.key, "runtime.build"), "Runtime build does not match expected build.", repo)
    if not ready.value:
        return GateResult(Stage.RUNTIME_PROVEN, GateState.BLOCKED, evidence_keys=(ready.key,), detail="Runtime predicates are not satisfied.", repo_id=repo)
    return GateResult(Stage.RUNTIME_PROVEN, GateState.PASS, evidence_keys=(ready.key, sample.key), repo_id=repo)


def _freshen(fact: Fact, evaluated_at: datetime | None) -> Fact:
    if evaluated_at and fact.fresh_until_utc and parse_utc(fact.fresh_until_utc) < evaluated_at:
        return Fact(**{**fact.__dict__, "state": FactState.STALE})
    return fact


def _eligible(fact: Fact | None) -> bool:
    return fact is not None and fact.state in {FactState.OBSERVED, FactState.DERIVED}


def _missing(facts: dict[str, Fact], keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(k for k in keys if not _eligible(facts.get(k)))


def _unknown(stage: Stage, keys: tuple[str, ...], repo: str | None,
             facts: dict[str, Fact]) -> GateResult:
    states = {facts[key].state for key in keys if key in facts}
    reason = (ReasonCode.EVIDENCE_CONFLICT if FactState.CONFLICT in states else
              ReasonCode.EVIDENCE_STALE if FactState.STALE in states else ReasonCode.COLLECTOR_UNAVAILABLE)
    return GateResult(stage, GateState.UNKNOWN, (reason,), keys,
                      f"Required evidence is unavailable for {stage.value}.", repo)
