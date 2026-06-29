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
DEFAULT_TRIGGER_FILE = Path("design/workflow_os_revisit_triggers.json")
DEFAULT_SECTION37_DECISION = Path("design/security/workflow_os_37_operator_decision.json")
VALID_SECTION37_STATUSES = {"closed_plan_only", "applied_with_evidence"}


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
    b0 = session_cost_probe.build_b0_status(argparse.Namespace(baseline=args.b0_baseline))
    section37 = check_section37(args.section37_decision)
    triggers = check_triggers(args.trigger_file)
    ready = bool(b0["ready"] and section37["ready"] and triggers["ready"])
    return {
        "schema_version": 1,
        "ready": ready,
        "b0": b0,
        "section37": section37,
        "triggers": triggers,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed Workflow OS completion check")
    parser.add_argument("--b0-baseline", type=Path, default=DEFAULT_B0_BASELINE)
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
