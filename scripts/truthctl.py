"""TruthDeck command-line interface and shared request orchestration."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from truthdeck_collectors import (
    CollectorError, CollectorResult, CollectorRun, Policy, collect_concurrently, collect_plan,
)
from truthdeck_gates import evaluate, overall_state
from truthdeck_git import collect_git
from truthdeck_github import collect_github
from truthdeck_handoff import collect_artifact, collect_review, verify_handoff
from truthdeck_model import (
    GateState, NextAction, Scope, Snapshot, Stage, TOOL_VERSION, canonical_json,
    snapshot_to_dict, utc_now,
)
from truthdeck_profiles import RegistryError, apply_narrowing, load_registry, resolve_profile
from truthdeck_render import render_diff, render_snapshot
from truthdeck_runtime import collect_runtime
from truthdeck_storage import read_snapshot, store_snapshot, write_explicit

EXIT_BY_STATE = {GateState.PASS: 0, GateState.HOLD: 10, GateState.BLOCKED: 11, GateState.UNKNOWN: 12}


class BoundaryRefusal(ValueError):
    pass


def build_snapshot(*, repos: list[Path], registry_path: Path, plan: Path | None = None,
                   pr: int | None = None, review_packet: Path | None = None,
                   review_result: Path | None = None, profile_name: str | None = None,
                   artifacts: tuple[Path, ...] = (), require: tuple[Stage, ...] | None = None,
                   observed_at_utc: str | None = None) -> Snapshot:
    observed = observed_at_utc or utc_now()
    registry, policy_digest = load_registry(registry_path)
    defaults = registry["defaults"]
    policy = Policy(float(defaults["command_timeout_s"]), float(defaults["total_deadline_s"]),
                    int(defaults["max_output_bytes"]), 4)
    deadline = time.monotonic() + policy.total_deadline_s
    all_facts = []
    all_runs: list[CollectorRun] = []
    required = require
    scope_repos: list[str] = []
    boundaries = ["advisory_only", "no_application_repo_writes", "no_broker_or_order_path", "no_automatic_actions"]
    diagnostics: list[str] = []
    for repo in repos:
        repo = repo.resolve(strict=True)
        if not (repo / ".git").exists() and not _inside_worktree(repo):
            raise BoundaryRefusal(f"not a Git repository: {repo}")
        try:
            git_result = collect_git(repo, base_ref=str(defaults["base_ref"]), observed_at_utc=observed, deadline=deadline)
        except CollectorError:
            git_result = collect_git(repo, base_ref="HEAD", observed_at_utc=observed, deadline=deadline)
        all_facts.extend(git_result.facts)
        all_runs.append(git_result.run)
        repo_id = git_result.run.repo_id or repo.name
        scope_repos.append(repo_id)
        selected_name, selected = resolve_profile(registry, repo, profile_name)
        selected = apply_narrowing(selected, repo / ".truthdeck-policy.json")
        if required is None:
            required = tuple(Stage(x) for x in selected["required_stages"])
        collectors = {}
        if plan is not None:
            resolved_plan = _contained(plan, repo)
            collectors["plan"] = lambda _d, p=resolved_plan, rid=repo_id: collect_plan(p, observed_at_utc=observed, repo_id=rid)
        else:
            diagnostics.append(f"{repo_id}: no explicit plan")
        if pr is not None:
            collectors["github"] = lambda d, r=repo, rid=repo_id: _capture(
                "github", rid, lambda: collect_github(r, pr=pr, observed_at_utc=observed, deadline=d, repo_id=rid)
            )
        if review_packet is not None or review_result is not None:
            if not (review_packet and review_result):
                raise ValueError("review requires both --review-packet and --review-result")
            head = next(f.value for f in git_result.facts if f.key == "implementation.head")
            facts = collect_review(review_packet, review_result, expected_head=head,
                                   observed_at_utc=observed, repo_id=repo_id)
            all_facts.extend(facts)
            all_runs.append(CollectorRun("review", "1", 0, 0, repo_id=repo_id))
        probe_ids = list(selected["runtime_probe_ids"])
        collectors["runtime"] = lambda d, r=repo, rid=repo_id, probes=probe_ids, applicable=bool(selected["runtime_applicable"]): _capture(
            "runtime", rid, lambda: collect_runtime(r, probe_id=probes[0] if probes else None,
                                                      observed_at_utc=observed, deadline=d, repo_id=rid,
                                                      runtime_applicable=applicable)
        )
        for index, artifact in enumerate(artifacts):
            resolved_artifact = _contained(artifact, repo)
            collectors[f"artifact-{index}"] = lambda _d, p=resolved_artifact, rid=repo_id: collect_artifact(
                p, observed_at_utc=observed, repo_id=rid
            )
        for result in collect_concurrently(collectors, policy=policy, deadline=deadline):
            all_facts.extend(result.facts)
            all_runs.append(result.run)
        diagnostics.append(f"profile:{selected_name}")
    required = required or tuple(Stage)
    facts = tuple(sorted(all_facts, key=lambda x: (x.repo_id or "", x.key, x.source_type)))
    gates, action = evaluate(facts, required=required)
    source_digest = hashlib.sha256(canonical_json([f.evidence_sha256 for f in facts])).hexdigest()
    snapshot = Snapshot(
        observed_at_utc=observed, scope=Scope(tuple(scope_repos), str(plan) if plan else None, pr, None, tuple(required)),
        tool={"version": TOOL_VERSION, "policy_digest_sha256": policy_digest}, facts=facts,
        conflicts=(), gates=gates, next_action=action, boundaries=tuple(boundaries),
        collector_runs=tuple(sorted(all_runs, key=lambda x: (x.repo_id or "", x.collector_id))),
        source_digest_sha256=source_digest,
    )
    return snapshot.with_content_id()


def re_evaluate(snapshot: Snapshot, *, evaluated_at: datetime | None = None) -> Snapshot:
    gates, action = evaluate(snapshot.facts, required=snapshot.scope.required_stages,
                             evaluated_at=evaluated_at or datetime.now(UTC))
    return dataclasses.replace(snapshot, gates=gates, next_action=action)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            print(TOOL_VERSION)
            return 0
        if args.command == "validate-registry":
            _, digest = load_registry(args.registry)
            print(json.dumps({"valid": True, "policy_digest_sha256": digest}, sort_keys=True) if args.json else f"valid: {digest}")
            return 0
        if args.command == "verify-handoff":
            fact, detail = verify_handoff(args.path, args.sha256, observed_at_utc=utc_now(), repo=args.repo)
            payload = {"fact": dataclasses.asdict(fact), **detail}
            print(json.dumps(payload, sort_keys=True, default=str) if args.json else f"valid: {detail['valid']}\nsha256: {detail['sha256']}")
            return 11 if not detail["valid"] else 0 if detail["continuation_state"] == "PASS" else 10
        if args.command == "diff":
            before = re_evaluate(read_snapshot(args.before))
            after = re_evaluate(read_snapshot(args.after))
            if args.json:
                print(json.dumps({"before": snapshot_to_dict(before), "after": snapshot_to_dict(after)}, sort_keys=True))
            else:
                print(render_diff(before, after))
            return 0
        if args.command == "next":
            snapshot = re_evaluate(read_snapshot(args.snapshot))
            if args.json:
                print(json.dumps(dataclasses.asdict(snapshot.next_action), sort_keys=True, default=str))
            else:
                print(snapshot.next_action.summary)
            return EXIT_BY_STATE.get(overall_state(snapshot.gates, snapshot.scope.required_stages), 0)
        if args.command == "snapshot":
            required = tuple(Stage(x) for x in args.require.split(",")) if args.require else None
            snapshot = build_snapshot(repos=args.repo, registry_path=args.registry, plan=args.plan, pr=args.pr,
                                      review_packet=args.review_packet, review_result=args.review_result,
                                      profile_name=args.profile, artifacts=tuple(args.artifact or ()), require=required)
            artifact = digest = None
            if not args.no_store:
                artifact, digest = store_snapshot(snapshot, root=args.state_root)
            if args.output:
                write_explicit(args.output, canonical_json(snapshot_to_dict(snapshot)) + b"\n")
            if args.json:
                print(json.dumps(snapshot_to_dict(snapshot), sort_keys=True, ensure_ascii=False))
            else:
                print(render_snapshot(snapshot, artifact_path=str(artifact) if artifact else None, digest=digest))
            return EXIT_BY_STATE.get(overall_state(snapshot.gates, snapshot.scope.required_stages), 0)
    except BoundaryRefusal as exc:
        return _error(str(exc), 3, getattr(args, "json", False))
    except (ValueError, RegistryError, OSError, json.JSONDecodeError) as exc:
        return _error(str(exc), 2, getattr(args, "json", False))
    except CollectorError as exc:
        return _error(str(exc), 124 if "deadline" in str(exc).lower() else 12, getattr(args, "json", False))
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="truthctl")
    subs = parser.add_subparsers(dest="command", required=True)
    snapshot = subs.add_parser("snapshot")
    snapshot.add_argument("--repo", type=Path, action="append", required=True)
    snapshot.add_argument("--registry", type=Path, default=_default_registry())
    snapshot.add_argument("--state-root", type=Path)
    snapshot.add_argument("--plan", type=Path)
    snapshot.add_argument("--pr", type=int)
    snapshot.add_argument("--review-packet", type=Path)
    snapshot.add_argument("--review-result", type=Path)
    snapshot.add_argument("--artifact", type=Path, action="append")
    snapshot.add_argument("--profile")
    snapshot.add_argument("--require")
    snapshot.add_argument("--no-store", action="store_true")
    snapshot.add_argument("--output", type=Path)
    snapshot.add_argument("--json", action="store_true")
    next_parser = subs.add_parser("next")
    next_parser.add_argument("--snapshot", type=Path, required=True)
    next_parser.add_argument("--json", action="store_true")
    diff = subs.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--json", action="store_true")
    handoff = subs.add_parser("verify-handoff")
    handoff.add_argument("--path", type=Path, required=True)
    handoff.add_argument("--sha256", required=True)
    handoff.add_argument("--repo", type=Path)
    handoff.add_argument("--json", action="store_true")
    validate = subs.add_parser("validate-registry")
    validate.add_argument("--registry", type=Path, default=_default_registry())
    validate.add_argument("--json", action="store_true")
    subs.add_parser("version")
    return parser


def _default_registry() -> Path:
    installed = Path.home() / ".truthdeck" / "registry.json"
    return installed if installed.exists() else Path(__file__).resolve().parents[1] / "templates" / "truthdeck.registry.json.template"


def _contained(path: Path, repo: Path) -> Path:
    candidate = path if path.is_absolute() else repo / path
    resolved = candidate.resolve(strict=True)
    if resolved != repo and repo not in resolved.parents:
        raise BoundaryRefusal(f"path escapes repository: {path}")
    return resolved


def _inside_worktree(repo: Path) -> bool:
    import subprocess
    return subprocess.run(("git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"), capture_output=True).returncode == 0


def _capture(collector_id: str, repo_id: str, operation) -> CollectorResult:
    try:
        return operation()
    except CollectorError as exc:
        return CollectorResult(collector_id, (), CollectorRun(collector_id, "1", 0, None,
                                                               diagnostics=(exc.reason.value, str(exc)[:200]), repo_id=repo_id))


def _error(message: str, code: int, as_json: bool) -> int:
    safe = message.replace(str(Path.home()), "~")[:500]
    print(json.dumps({"error": safe, "exit_code": code}) if as_json else f"error: {safe}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
