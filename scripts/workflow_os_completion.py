#!/usr/bin/env python3
"""Fail-closed completion check for the Workflow OS plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import idea_digest
import session_cost_probe


DEFAULT_B0_BASELINE = Path("design/baselines/workflow_os_b0_mixed_sessions.json")
DEFAULT_SCOPE_DECISION = Path("design/decisions/2026-06-29_workflow_os_shipped_scope_close.json")
DEFAULT_TRIGGER_FILE = Path("design/workflow_os_revisit_triggers.json")
DEFAULT_SECTION37_DECISION = Path("design/security/workflow_os_37_operator_decision.json")
VALID_SECTION37_STATUSES = {"closed_plan_only", "applied_with_evidence"}
VALID_SCOPE_STATUSES = {"closed_as_future_gated_work"}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return data


def check_section37(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "decision": str(path),
        "ready": False,
        "errors": [],
    }
    if not path.exists():
        status["errors"].append(f"missing operator decision artifact: {path}")
        return status
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        status["errors"].append(str(exc))
        return status

    if data.get("schema_version") != 1:
        status["errors"].append("schema_version must be 1")
    if data.get("kind") != "workflow_os_37_operator_decision":
        status["errors"].append("kind must be workflow_os_37_operator_decision")
    if data.get("status") not in VALID_SECTION37_STATUSES:
        status["errors"].append(
            "status must be one of: " + ", ".join(sorted(VALID_SECTION37_STATUSES))
        )
    if data.get("operator_go") is not True:
        status["errors"].append("operator_go must be true")
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        status["errors"].append("evidence must be a non-empty list")
    elif not all(isinstance(item, str) and item.strip() for item in evidence):
        status["errors"].append("all evidence entries must be non-empty text")

    status["operator_status"] = data.get("status")
    status["ready"] = not status["errors"]
    return status


def check_scope_decision(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "decision": str(path),
        "ready": False,
        "errors": [],
        "future_gated_work": [],
    }
    if not path.exists():
        status["errors"].append(f"missing scope decision artifact: {path}")
        return status
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        status["errors"].append(str(exc))
        return status

    if data.get("schema_version") != 1:
        status["errors"].append("schema_version must be 1")
    if data.get("kind") != "workflow_os_shipped_scope_close":
        status["errors"].append("kind must be workflow_os_shipped_scope_close")
    if data.get("status") not in VALID_SCOPE_STATUSES:
        status["errors"].append(
            "status must be one of: " + ", ".join(sorted(VALID_SCOPE_STATUSES))
        )
    if data.get("operator_decision") is not True:
        status["errors"].append("operator_decision must be true")
    future = data.get("future_gated_work")
    if not isinstance(future, list) or not future:
        status["errors"].append("future_gated_work must be a non-empty list")
        future = []
    elif not all(isinstance(item, str) and item.strip() for item in future):
        status["errors"].append("all future_gated_work entries must be non-empty text")
    required = {
        "b0_headroom_rtk",
        "section37_apply",
        "manual_triggers",
    }
    missing = sorted(required - set(future))
    if missing:
        status["errors"].append("future_gated_work missing: " + ", ".join(missing))

    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        status["errors"].append("evidence must be a non-empty list")
    elif not all(isinstance(item, str) and item.strip() for item in evidence):
        status["errors"].append("all evidence entries must be non-empty text")

    status["future_gated_work"] = future
    status["ready"] = not status["errors"]
    return status


def check_b0(path: Path, scope_decision: dict[str, Any]) -> dict[str, Any]:
    b0 = session_cost_probe.build_b0_status(argparse.Namespace(baseline=path))
    if b0["ready"]:
        return b0
    if scope_decision["ready"] and "b0_headroom_rtk" in scope_decision["future_gated_work"]:
        return {
            **b0,
            "deferred_errors": b0["errors"],
            "errors": [],
            "ready": True,
            "closed_as_future_gated_work": True,
            "closure_decision": scope_decision["decision"],
        }
    return b0


def check_triggers(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "trigger_file": str(path),
        "ready": False,
        "pending": [],
        "errors": [],
    }
    if not path.exists():
        status["errors"].append(f"missing trigger file: {path}")
        return status
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        status["errors"].append(str(exc))
        return status

    base = path.resolve().parent.parent
    for item in data.get("items", []):
        if not isinstance(item, dict):
            status["errors"].append("trigger item must be an object")
            continue
        item_id = str(item.get("id", ""))
        item_status = str(item.get("status", "")).lower()
        if item_status in {"completed", "killed"}:
            continue
        evaluated, reason = idea_digest.evaluate_trigger(item.get("trigger_predicate", {}), base)
        status["pending"].append(
            {
                "id": item_id,
                "status": evaluated,
                "reason": reason,
            }
        )

    status["ready"] = not status["errors"] and not status["pending"]
    return status


def build_completion_status(args: argparse.Namespace) -> dict[str, Any]:
    scope_decision = check_scope_decision(args.scope_decision)
    b0 = check_b0(args.b0_baseline, scope_decision)
    section37 = check_section37(args.section37_decision)
    triggers = check_triggers(args.trigger_file)
    ready = bool(scope_decision["ready"] and b0["ready"] and section37["ready"] and triggers["ready"])
    return {
        "schema_version": 1,
        "ready": ready,
        "b0": b0,
        "scope_decision": scope_decision,
        "section37": section37,
        "triggers": triggers,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed Workflow OS completion check")
    parser.add_argument("--b0-baseline", type=Path, default=DEFAULT_B0_BASELINE)
    parser.add_argument("--scope-decision", type=Path, default=DEFAULT_SCOPE_DECISION)
    parser.add_argument("--trigger-file", type=Path, default=DEFAULT_TRIGGER_FILE)
    parser.add_argument("--section37-decision", type=Path, default=DEFAULT_SECTION37_DECISION)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_completion_status(args)
    if args.output:
        write_json(args.output, status)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
