"""Closed-world adapter validation and fail-closed impact selection."""

from __future__ import annotations

import fnmatch
import math
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .schemas import (
    ADAPTER_SCHEMA,
    CONTRACT_VERSION,
    PREFLIGHT_SCHEMA,
    SHA40,
    SHA256,
    ContractError,
    contract_hash,
    require_exact_keys,
    require_string,
    require_string_list,
    validate_version_range,
)

VALID_RISKS = ("R0", "R1", "R2", "R3")
VALID_TIERS = ("T0", "T1", "T2", "T3", "T4")
VALID_ESCALATIONS = ("focused", "wide", "full")


def normalize_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ContractError(f"invalid repository-relative path: {raw!r}")
    if path.parts and path.parts[0].endswith(":"):
        raise ContractError(f"drive-qualified path is forbidden: {raw!r}")
    return path.as_posix()


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(
        path.lower(), pattern.lower()
    )


def _max_escalation(left: str, right: str) -> str:
    return VALID_ESCALATIONS[
        max(VALID_ESCALATIONS.index(left), VALID_ESCALATIONS.index(right))
    ]


def validate_adapter(adapter: Mapping[str, Any]) -> str:
    require_exact_keys(
        adapter,
        {
            "schema_version",
            "repository",
            "owners",
            "shared_contract",
            "commands",
            "artifact_root",
            "platforms",
            "critical_rules",
            "mandatory_bundles",
            "bundles",
            "risk_to_tiers",
            "exact_base_ttl_seconds",
            "scheduled_full_health",
            "dependency_pins",
            "required_check",
            "candidate_mode",
            "activation",
            "cost",
            "rollback_to_full",
        },
        "adapter",
    )
    if adapter["schema_version"] != ADAPTER_SCHEMA:
        raise ContractError(f"adapter schema must be {ADAPTER_SCHEMA}")
    require_string(adapter["repository"], "repository")
    require_string_list(adapter["owners"], "owners")
    shared_contract = adapter["shared_contract"]
    if not isinstance(shared_contract, dict):
        raise ContractError("shared_contract must be a mapping")
    validate_version_range(shared_contract)
    commands = adapter["commands"]
    if not isinstance(commands, dict):
        raise ContractError("commands must be a mapping")
    require_exact_keys(commands, {"t0", "local", "ci", "collect"}, "commands")
    for name, command in commands.items():
        require_string(command, f"commands.{name}")
    if (
        normalize_path(require_string(adapter["artifact_root"], "artifact_root"))
        != adapter["artifact_root"]
    ):
        raise ContractError("artifact_root must be a normalized repository path")
    platforms = adapter["platforms"]
    if not isinstance(platforms, dict):
        raise ContractError("platforms must be a mapping")
    require_exact_keys(platforms, {"os", "python", "node", "runtime"}, "platforms")
    for name, identities in platforms.items():
        require_string_list(identities, f"platforms.{name}", allow_empty=True)
    rules = adapter["critical_rules"]
    if not isinstance(rules, list) or not rules:
        raise ContractError("critical_rules must be a non-empty list")
    rule_ids: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ContractError("critical rule must be a mapping")
        require_exact_keys(
            rule, {"id", "class", "escalation", "patterns", "tests"}, "critical rule"
        )
        rule_ids.append(require_string(rule["id"], "critical rule id"))
        require_string(rule["class"], "critical rule class")
        if rule["escalation"] not in VALID_ESCALATIONS:
            raise ContractError("critical rule escalation is invalid")
        require_string_list(rule["patterns"], "critical rule patterns")
        require_string_list(rule["tests"], "critical rule tests", allow_empty=True)
    if rule_ids != sorted(set(rule_ids)):
        raise ContractError("critical rule IDs must be sorted and unique")
    bundles = adapter["bundles"]
    mandatory = adapter["mandatory_bundles"]
    if not isinstance(bundles, dict) or not isinstance(mandatory, dict):
        raise ContractError("bundles and mandatory_bundles must be mappings")
    if set(mandatory) != set(VALID_RISKS):
        raise ContractError("mandatory_bundles must define R0-R3 exactly")
    for name, tests in bundles.items():
        require_string(name, "bundle name")
        require_string_list(tests, f"bundle {name}")
    for risk, names in mandatory.items():
        require_string_list(names, f"mandatory_bundles.{risk}", allow_empty=True)
        missing = sorted(set(names) - set(bundles))
        if missing:
            raise ContractError(
                f"mandatory bundles are undefined: {', '.join(missing)}"
            )
    risk_to_tiers = adapter["risk_to_tiers"]
    if not isinstance(risk_to_tiers, dict) or set(risk_to_tiers) != set(VALID_RISKS):
        raise ContractError("risk_to_tiers must define R0-R3 exactly")
    for risk, tiers in risk_to_tiers.items():
        require_string_list(tiers, f"risk_to_tiers.{risk}")
        if any(tier not in VALID_TIERS for tier in tiers):
            raise ContractError("risk_to_tiers contains an invalid tier")
    ttl = adapter["exact_base_ttl_seconds"]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 0:
        raise ContractError("exact_base_ttl_seconds must be a non-negative integer")
    health = adapter["scheduled_full_health"]
    if not isinstance(health, dict):
        raise ContractError("scheduled_full_health must be a mapping")
    require_exact_keys(health, {"schedule_utc", "command"}, "scheduled_full_health")
    require_string(health["schedule_utc"], "scheduled_full_health.schedule_utc")
    require_string(health["command"], "scheduled_full_health.command")
    pins = adapter["dependency_pins"]
    if not isinstance(pins, dict) or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in pins.items()
    ):
        raise ContractError("dependency_pins must be a string mapping")
    require_string(adapter["required_check"], "required_check")
    if adapter["candidate_mode"] not in {"full", "selected"}:
        raise ContractError("candidate_mode must be full or selected")
    activation = adapter["activation"]
    if not isinstance(activation, dict):
        raise ContractError("activation must be a mapping")
    require_exact_keys(
        activation,
        {"verdict", "evidence_sha256", "reviewed_head_sha"},
        "activation",
    )
    if activation["verdict"] not in {"HOLD", "PASS"}:
        raise ContractError("activation.verdict must be HOLD or PASS")
    if not isinstance(activation["evidence_sha256"], str) or not SHA256.fullmatch(
        activation["evidence_sha256"]
    ):
        raise ContractError("activation.evidence_sha256 is invalid")
    if not isinstance(activation["reviewed_head_sha"], str) or not SHA40.fullmatch(
        activation["reviewed_head_sha"]
    ):
        raise ContractError("activation.reviewed_head_sha is invalid")
    if adapter["candidate_mode"] == "selected" and activation["verdict"] != "PASS":
        raise ContractError("selected candidate mode requires PASS activation evidence")
    cost = adapter["cost"]
    if not isinstance(cost, dict):
        raise ContractError("cost must be a mapping")
    require_exact_keys(cost, {"rate", "currency", "source", "effective_date"}, "cost")
    if (
        isinstance(cost["rate"], bool)
        or not isinstance(cost["rate"], (int, float))
        or not math.isfinite(float(cost["rate"]))
        or cost["rate"] < 0
    ):
        raise ContractError("cost.rate must be non-negative")
    for key in ("currency", "source", "effective_date"):
        require_string(cost[key], f"cost.{key}")
    require_string(adapter["rollback_to_full"], "rollback_to_full")
    return contract_hash(adapter)


def build_preflight(
    *,
    adapter: Mapping[str, Any],
    changes: Sequence[Mapping[str, str]],
    risk_class: str,
    base_sha: str,
    head_sha: str,
    graph_status: str,
) -> dict[str, Any]:
    adapter_sha = validate_adapter(adapter)
    if risk_class not in VALID_RISKS:
        raise ContractError("risk_class must be R0-R3")
    if (
        not SHA40.fullmatch(base_sha)
        or not SHA40.fullmatch(head_sha)
        or base_sha == head_sha
    ):
        raise ContractError("base/head must be distinct lowercase commit SHAs")
    if graph_status not in {"fresh", "stale", "missing", "corrupt"}:
        raise ContractError("graph_status is invalid")
    if not changes:
        raise ContractError("changes must be non-empty")
    normalized: list[dict[str, Any]] = []
    selected: dict[str, set[str]] = {}
    escalation = "focused"
    unknown: list[str] = []
    t0_only = bool(changes)
    for bundle in adapter["mandatory_bundles"][risk_class]:
        for nodeid in adapter["bundles"][bundle]:
            selected.setdefault(nodeid, set()).add(f"mandatory:{bundle}")
    for change in changes:
        if not isinstance(change, dict):
            raise ContractError("changes must contain mappings")
        require_exact_keys(change, {"path", "status", "sha256"}, "change")
        path = normalize_path(change["path"])
        status = change["status"]
        if status not in {"A", "M", "D", "R"}:
            raise ContractError("change status is invalid")
        if not isinstance(change["sha256"], str) or not SHA256.fullmatch(
            change["sha256"]
        ):
            raise ContractError("change sha256 is invalid")
        matched = [
            rule
            for rule in adapter["critical_rules"]
            if any(_matches(path, pattern) for pattern in rule["patterns"])
        ]
        if not matched:
            classification = "unknown"
            path_escalation = "full"
            unknown.append(path)
        else:
            classification = matched[0]["class"]
            if classification != "t0-only" or any(
                rule["class"] != "t0-only" for rule in matched
            ):
                t0_only = False
            path_escalation = "focused"
            for rule in matched:
                path_escalation = _max_escalation(path_escalation, rule["escalation"])
                for nodeid in rule["tests"]:
                    selected.setdefault(nodeid, set()).add(f"rule:{rule['id']}")
        if status in {"D", "R"}:
            path_escalation = "full"
        escalation = _max_escalation(escalation, path_escalation)
        normalized.append(
            {
                "path": path,
                "status": status,
                "sha256": change["sha256"],
                "class": classification,
            }
        )
    if unknown:
        t0_only = False
    if t0_only:
        selected = {}
        escalation = "focused"
    elif graph_status in {"stale", "missing", "corrupt"} and normalized:
        escalation = _max_escalation(escalation, "wide")
    if not t0_only and (unknown or adapter["candidate_mode"] == "full"):
        escalation = "full"
    selected_tests = [
        {"nodeid": nodeid, "reasons": sorted(reasons)}
        for nodeid, reasons in sorted(selected.items())
    ]
    if normalized and not t0_only and not selected_tests:
        raise ContractError("non-empty diff selected no tests")
    if t0_only:
        command = adapter["commands"]["t0"]
    elif escalation == "focused":
        command = adapter["commands"]["local"]
    else:
        command = adapter["commands"]["ci"]
    result: dict[str, Any] = {
        "schema_version": PREFLIGHT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "repository": adapter["repository"],
        "adapter_sha256": adapter_sha,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "risk_class": risk_class,
        "graph_status": graph_status,
        "changed_files": sorted(normalized, key=lambda item: item["path"]),
        "selected_tests": selected_tests,
        "unknown_surfaces": sorted(unknown),
        "t0_only": t0_only,
        "escalation": escalation,
        "command": command,
    }
    result["preflight_sha256"] = contract_hash(result)
    return result
