#!/usr/bin/env python3
"""Workflow OS Headroom/RTK measurement gate.

This script is intentionally measurement-only. It never wraps an agent, edits
global config, starts a proxy, or installs hooks.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_repo_path(path_text: str, repo_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return repo_root / path


def load_b0_source_jsonls(baseline: Path, repo_root: Path) -> list[dict[str, str]]:
    data = _read_json(baseline)
    if data.get("method") != "B0":
        raise ValueError(f"{baseline}: expected method=B0")
    mixed = data.get("mixed_session_baseline")
    if not isinstance(mixed, dict):
        raise ValueError(f"{baseline}: missing mixed_session_baseline")
    sessions = mixed.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"{baseline}: mixed_session_baseline.sessions must be non-empty")

    sources = []
    for session in sessions:
        if not isinstance(session, dict):
            raise ValueError(f"{baseline}: session entry must be an object")
        session_id = session.get("id")
        source = session.get("source")
        if not isinstance(session_id, str) or not isinstance(source, str):
            raise ValueError(f"{baseline}: each session needs id and source")
        session_json = _resolve_repo_path(source, repo_root)
        measured = _read_json(session_json)
        jsonl = measured.get("source_jsonl")
        if not isinstance(jsonl, str) or not jsonl:
            raise ValueError(f"{session_json}: missing source_jsonl")
        jsonl_path = Path(jsonl)
        if not jsonl_path.exists():
            raise ValueError(f"{session_json}: source_jsonl does not exist: {jsonl_path}")
        sources.append({"id": session_id, "jsonl": str(jsonl_path)})
    return sources


def run_headroom_audit(headroom_exe: str, sources: list[dict[str, str]]) -> dict[str, Any]:
    resolved = shutil.which(headroom_exe) or headroom_exe
    with tempfile.TemporaryDirectory(prefix="workflow-os-b0-headroom-") as temp:
        temp_dir = Path(temp)
        for source in sources:
            source_path = Path(source["jsonl"])
            shutil.copy2(source_path, temp_dir / source_path.name)
        cp = subprocess.run(
            [resolved, "audit-reads", "--path", str(temp_dir), "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    if cp.returncode != 0:
        return {
            "available": False,
            "command": [resolved, "audit-reads", "--path", "<temp-b0-jsonls>", "--format", "json"],
            "returncode": cp.returncode,
            "stderr": cp.stderr.strip(),
            "stdout": cp.stdout.strip()[:1000],
        }
    try:
        metrics = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "command": [resolved, "audit-reads", "--path", "<temp-b0-jsonls>", "--format", "json"],
            "returncode": cp.returncode,
            "stderr": f"invalid JSON: {exc}",
            "stdout": cp.stdout.strip()[:1000],
        }
    return {
        "available": True,
        "command": [resolved, "audit-reads", "--path", "<temp-b0-jsonls>", "--format", "json"],
        "metrics": metrics,
    }


def probe_rtk(rtk_exe: str) -> dict[str, Any]:
    resolved = shutil.which(rtk_exe)
    if not resolved:
        return {
            "available": False,
            "command": [rtk_exe, "--version"],
            "reason": "rtk executable not found on PATH",
        }
    cp = subprocess.run([resolved, "--version"], capture_output=True, text=True, check=False)
    return {
        "available": cp.returncode == 0,
        "command": [resolved, "--version"],
        "returncode": cp.returncode,
        "stdout": cp.stdout.strip(),
        "stderr": cp.stderr.strip(),
    }


def summarize_decision(headroom: dict[str, Any], rtk: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if headroom.get("available"):
        metrics = headroom.get("metrics", {})
        reasons.append(
            "headroom audit-reads measured B0 read traffic, but this is an opportunity audit, not a full replay with output/cost and artifact equivalence"
        )
        if metrics.get("dedup_identical_bytes", 0) == 0 and metrics.get("subset_bytes", 0) == 0:
            reasons.append("B0 selected sessions showed no identical/subset read dedup opportunity")
    else:
        reasons.append("headroom was not available for a local B0 audit")
    if not rtk.get("available"):
        reasons.append("rtk executable was not available locally, so no RTK command-output benchmark was run")
    reasons.append("Workflow OS ship gate requires total cost reduction >=15 percent with no quality regression before default-on")
    return {
        "default_on": False,
        "ship_gate_pass": False,
        "decision": "PARK",
        "reasons": reasons,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    baseline = args.baseline if args.baseline.is_absolute() else repo_root / args.baseline
    sources = load_b0_source_jsonls(baseline, repo_root)
    headroom = run_headroom_audit(args.headroom_exe, sources) if not args.skip_headroom else {"available": False, "reason": "skipped"}
    rtk = probe_rtk(args.rtk_exe)
    return {
        "schema_version": 1,
        "generated_at": _now(),
        "risk_class": "R1",
        "scope": "Workflow OS token proxy benchmark; measurement-only; no proxy, wrapper, hook, or global config change",
        "baseline": str(baseline),
        "sessions": sources,
        "headroom": headroom,
        "rtk": rtk,
        "decision": summarize_decision(headroom, rtk),
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Workflow OS Headroom/RTK benchmark gate")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--baseline", type=Path, default=Path("design/baselines/workflow_os_b0_mixed_sessions.json"))
    parser.add_argument("--headroom-exe", default="headroom")
    parser.add_argument("--rtk-exe", default="rtk")
    parser.add_argument("--skip-headroom", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = build_report(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    write_json(args.output, report)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
