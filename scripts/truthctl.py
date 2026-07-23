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

from truthdeck_collectors import (
    CollectorError, CollectorResult, CollectorRun, CollectorTimeout, Policy,
    collect_concurrently, collect_plan,
)
from truthdeck_gates import evaluate, overall_state
from truthdeck_gates import find_conflicts
from truthdeck_git import collect_git
from truthdeck_github import collect_github
from truthdeck_handoff import collect_artifact, collect_review, verify_handoff
from truthdeck_install import status as installation_status
from truthdeck_model import (
    GateState, Scope, Snapshot, Stage, TOOL_VERSION, canonical_json, make_fact,
    snapshot_to_dict, utc_now,
)
from truthdeck_profiles import (
    RegistryError, apply_narrowing, load_registry, resolve_profile, resolve_task_alias,
)
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
                   installation_home: Path | None = None,
                   observed_at_utc: str | None = None) -> Snapshot:
    observed = observed_at_utc or utc_now()
    registry, policy_digest = load_registry(registry_path)
    defaults = registry["defaults"]
    policy = Policy(float(defaults["command_timeout_s"]), float(defaults["total_deadline_s"]),
                    int(defaults["max_output_bytes"]), 4)
    deadline = time.monotonic() + policy.total_deadline_s * min(max(1, len(repos)), 2)
    resolved_repos = [repo.resolve(strict=True) for repo in repos]
    resolved_plan = None
    if plan is not None:
        candidate = plan if plan.is_absolute() else resolved_repos[0] / plan
        resolved_plan = candidate.resolve(strict=True)
        if not any(resolved_plan == repo or repo in resolved_plan.parents for repo in resolved_repos):
            raise BoundaryRefusal(f"plan path escapes requested repositories: {plan}")
    all_facts = []
    all_runs: list[CollectorRun] = []
    required = require
    scope_repos: list[str] = []
    boundaries = ["advisory_only", "no_application_repo_writes", "no_broker_or_order_path", "no_automatic_actions"]
    for repo in resolved_repos:
        if not (repo / ".git").exists():
            raise BoundaryRefusal(f"not a Git repository: {repo}")
        git_result = collect_git(repo, base_ref=str(defaults["base_ref"]), observed_at_utc=observed,
                                 deadline=deadline, command_timeout_s=policy.command_timeout_s,
                                 max_output_bytes=policy.max_output_bytes)
        all_facts.extend(git_result.facts)
        all_runs.append(git_result.run)
        repo_id = git_result.run.repo_id or repo.name
        scope_repos.append(repo_id)
        selected_name, selected = resolve_profile(registry, repo, profile_name, repo_id)
        selected = apply_narrowing(selected, repo / ".truthdeck-policy.json")
        allowed_collectors = set(selected["collectors"])
        if "git" not in allowed_collectors:
            raise RegistryError(f"profile {selected_name} must retain the git identity collector")
        if required is None:
            required = tuple(Stage(x) for x in selected["required_stages"])
        collectors = {}
        if plan is not None and "plan" in allowed_collectors:
            collectors["plan"] = lambda d, p=resolved_plan, rid=repo_id: _capture(
                "plan", rid, lambda: collect_plan(p, observed_at_utc=observed, repo_id=rid,
                                                   deadline=d, max_output_bytes=policy.max_output_bytes)
            )
        if pr is not None and "github" in allowed_collectors:
            required_checks = tuple(selected["required_checks"])
            collectors["github"] = lambda d, r=repo, rid=repo_id, checks=required_checks: _capture(
                "github", rid, lambda: collect_github(r, pr=pr, observed_at_utc=observed,
                                                       deadline=d, repo_id=rid, required_checks=checks,
                                                       command_timeout_s=policy.command_timeout_s,
                                                       max_output_bytes=policy.max_output_bytes)
            )
        if (review_packet is not None or review_result is not None) and "review" in allowed_collectors:
            if not (review_packet and review_result):
                raise ValueError("review requires both --review-packet and --review-result")
            head = next(f.value for f in git_result.facts if f.key == "implementation.head")
            collectors["review"] = lambda d, rid=repo_id, expected=head: _capture(
                "review", rid, lambda: _review_result(
                    review_packet, review_result, expected_head=expected, observed_at_utc=observed,
                    repo_id=rid, deadline=d, max_output_bytes=policy.max_output_bytes,
                )
            )
        probe_ids = list(selected["runtime_probe_ids"])
        implementation_head = next(f.value for f in git_result.facts if f.key == "implementation.head")
        if "runtime" in allowed_collectors or not bool(selected["runtime_applicable"]):
            collectors["runtime"] = lambda d, r=repo, rid=repo_id, probes=probe_ids, applicable=bool(selected["runtime_applicable"]), expected=implementation_head: _capture(
            "runtime", rid, lambda: collect_runtime(r, probe_ids=tuple(probes),
                                                      observed_at_utc=observed, deadline=d, repo_id=rid,
                                                      runtime_applicable=applicable, expected_build=expected,
                                                      command_timeout_s=policy.command_timeout_s,
                                                      max_output_bytes=policy.max_output_bytes)
            )
        if installation_home is not None and "installation" in allowed_collectors:
            collectors["installation"] = lambda d, home=installation_home, rid=repo_id: _capture(
                "installation", rid, lambda: _installation_result(home, observed, rid, d)
            )
        for index, artifact in enumerate(artifacts if "artifact" in allowed_collectors else ()):
            resolved_artifact = _contained(artifact, repo)
            collectors[f"artifact-{index}"] = lambda d, p=resolved_artifact, rid=repo_id: _capture(
                "artifact", rid, lambda: collect_artifact(
                    p, observed_at_utc=observed, repo_id=rid, deadline=d,
                    max_output_bytes=policy.max_output_bytes
                )
            )
        for result in collect_concurrently(collectors, policy=policy, deadline=deadline):
            all_facts.extend(result.facts)
            all_runs.append(result.run)
    required = required or tuple(Stage)
    facts = tuple(sorted(all_facts, key=lambda x: (x.repo_id or "", x.key, x.source_type)))
    conflicts = find_conflicts(facts)
    gates, action = evaluate(facts, required=required, repo_order=scope_repos)
    source_digest = hashlib.sha256(canonical_json([f.evidence_sha256 for f in facts])).hexdigest()
    snapshot = Snapshot(
        observed_at_utc=observed, scope=Scope(tuple(scope_repos), str(plan) if plan else None, pr, None, tuple(required)),
        tool={"version": TOOL_VERSION, "policy_digest_sha256": policy_digest}, facts=facts,
        conflicts=conflicts, gates=gates, next_action=action, boundaries=tuple(boundaries),
        collector_runs=tuple(sorted(all_runs, key=lambda x: (x.repo_id or "", x.collector_id))),
        source_digest_sha256=source_digest,
    )
    return snapshot.with_content_id()


def re_evaluate(snapshot: Snapshot, *, evaluated_at: datetime | None = None) -> Snapshot:
    gates, action = evaluate(snapshot.facts, required=snapshot.scope.required_stages,
                             evaluated_at=evaluated_at or datetime.now(UTC), repo_order=snapshot.scope.repos)
    return dataclasses.replace(snapshot, conflicts=find_conflicts(snapshot.facts), gates=gates, next_action=action)


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
            handoff_path, expected_sha, handoff_repo = _resolve_handoff_scope(args)
            fact, detail = verify_handoff(handoff_path, expected_sha, observed_at_utc=utc_now(), repo=handoff_repo)
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
            repos, plan, profile = _resolve_snapshot_scope(args)
            required = tuple(Stage(x) for x in args.require.split(",")) if args.require else None
            snapshot = build_snapshot(repos=repos, registry_path=args.registry, plan=plan, pr=args.pr,
                                      review_packet=args.review_packet, review_result=args.review_result,
                                      profile_name=profile, artifacts=tuple(args.artifact or ()), require=required,
                                      installation_home=args.installation_home)
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
    snapshot.add_argument("--repo", type=Path, action="append")
    snapshot.add_argument("--task")
    snapshot.add_argument("--registry", type=Path, default=_default_registry())
    snapshot.add_argument("--state-root", type=Path)
    snapshot.add_argument("--plan", type=Path)
    snapshot.add_argument("--pr", type=int)
    snapshot.add_argument("--review-packet", type=Path)
    snapshot.add_argument("--review-result", type=Path)
    snapshot.add_argument("--artifact", type=Path, action="append")
    snapshot.add_argument("--profile")
    snapshot.add_argument("--installation-home", type=Path)
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
    handoff_path = handoff.add_mutually_exclusive_group()
    handoff_path.add_argument("--handoff", "--path", dest="path", type=Path)
    handoff.add_argument("--sha256")
    handoff.add_argument("--repo", type=Path)
    handoff.add_argument("--task")
    handoff.add_argument("--registry", type=Path, default=_default_registry())
    handoff.add_argument("--json", action="store_true")
    validate = subs.add_parser("validate-registry")
    validate.add_argument("--registry", type=Path, default=_default_registry())
    validate.add_argument("--json", action="store_true")
    subs.add_parser("version")
    return parser


def _default_registry() -> Path:
    installed = Path.home() / ".truthdeck" / "registry.json"
    return installed if installed.exists() else Path(__file__).resolve().parents[1] / "templates" / "truthdeck.registry.json.template"


def _resolve_snapshot_scope(args) -> tuple[list[Path], Path | None, str | None]:
    if args.task:
        if args.repo or args.plan or args.profile:
            raise ValueError("--task cannot be combined with --repo, --plan, or --profile")
        registry, _ = load_registry(args.registry)
        alias = resolve_task_alias(registry, args.task)
        return [Path(item) for item in alias["repos"]], Path(alias["plan"]) if alias.get("plan") else None, alias.get("profile")
    if not args.repo:
        raise ValueError("snapshot requires --repo or --task")
    return args.repo, args.plan, args.profile


def _resolve_handoff_scope(args) -> tuple[Path, str, Path | None]:
    if args.task:
        if args.path or args.sha256 or args.repo:
            raise ValueError("--task cannot be combined with explicit handoff arguments")
        registry, _ = load_registry(args.registry)
        alias = resolve_task_alias(registry, args.task)
        if not alias.get("handoff"):
            raise ValueError(f"task alias {args.task} has no handoff")
        repos = alias["repos"]
        return Path(alias["handoff"]), alias["handoff_sha256"], Path(repos[0])
    if not args.path or not args.sha256:
        raise ValueError("verify-handoff requires --handoff and --sha256, or --task")
    return args.path, args.sha256, args.repo


def _contained(path: Path, repo: Path) -> Path:
    candidate = path if path.is_absolute() else repo / path
    resolved = candidate.resolve(strict=True)
    if resolved != repo and repo not in resolved.parents:
        raise BoundaryRefusal(f"path escapes repository: {path}")
    return resolved


def _capture(collector_id: str, repo_id: str, operation) -> CollectorResult:
    try:
        return operation()
    except CollectorError as exc:
        return CollectorResult(collector_id, (), CollectorRun(collector_id, "1", 0, None,
                                                               timed_out=isinstance(exc, CollectorTimeout),
                                                               diagnostics=(exc.reason.value, str(exc)[:200]), repo_id=repo_id))


def _review_result(packet: Path, reviewer_output: Path, **kwargs) -> CollectorResult:
    started = time.monotonic()
    facts = collect_review(packet, reviewer_output, **kwargs)
    return CollectorResult("review", facts, CollectorRun(
        "review", "1", int((time.monotonic() - started) * 1000), 0, repo_id=kwargs.get("repo_id"),
    ))


def _installation_result(home: Path, observed: str, repo_id: str, deadline: float) -> CollectorResult:
    started = time.monotonic()
    if time.monotonic() >= deadline:
        raise CollectorTimeout("installation collector deadline exceeded")
    result = installation_status(home=home)
    locator = str(home.resolve() / ".truthdeck" / "install-manifest.json")
    values = {
        "installation.state": result["state"],
        "installation.cli_installed": bool(result.get("cli_installed", False)),
        "installation.codex_skill_installed": bool(result.get("codex_skill_installed", False)),
        "installation.claude_skill_installed": bool(result.get("claude_skill_installed", False)),
        "mcp.codex_active": bool(result.get("mcp_codex_active", False)),
        "mcp.claude_active": bool(result.get("mcp_claude_active", False)),
    }
    facts = tuple(make_fact(key, value, source_type="installation", source_locator=locator,
                            observed_at_utc=observed, repo_id=repo_id, evidence=result)
                  for key, value in values.items())
    return CollectorResult("installation", facts, CollectorRun(
        "installation", "1", int((time.monotonic() - started) * 1000), 0, repo_id=repo_id,
    ))


def _error(message: str, code: int, as_json: bool) -> int:
    safe = message.replace(str(Path.home()), "~")[:500]
    print(json.dumps({"error": safe, "exit_code": code}) if as_json else f"error: {safe}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
