#!/usr/bin/env python3
"""Session cost and kernel-presence probe for the Agent Workflow OS plan.

The probe records facts only. It does not estimate savings as success unless a
caller supplies real usage/context numbers from Claude Code or another runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BEGIN_MARKER = "<!-- BEGIN AGENT-RULES:shared:v1 -->"
END_MARKER = "<!-- END AGENT-RULES:shared:v1 -->"
REQUIRED_KERNEL_NEEDLES = (
    "Token Budget Protocol",
    "Risk Classes",
    "Plan Lifecycle Hooks",
)
REQUIRED_B0_SESSION_IDS = (
    "read_heavy_audit",
    "multi_file_edit",
    "research_plan",
)
REQUIRED_B0_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cost_usd",
    "startup_context_tokens",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def file_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    data = path.read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "bytes": len(data),
        "lines": len(text.splitlines()),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def kernel_presence(path: Path) -> dict[str, Any]:
    metrics = file_metrics(path)
    if not metrics.get("exists"):
        return {**metrics, "managed_block": False, "needles": {}, "ok": False}
    text = _read_text(path)
    needles = {needle: (needle in text) for needle in REQUIRED_KERNEL_NEEDLES}
    ok = BEGIN_MARKER in text and END_MARKER in text and all(needles.values())
    return {**metrics, "managed_block": BEGIN_MARKER in text and END_MARKER in text, "needles": needles, "ok": ok}


def run_sync_check(repo_root: Path) -> dict[str, Any]:
    cmd = [sys.executable, str(repo_root / "scripts" / "sync_agent_rules.py"), "--check", "--quiet"]
    cp = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=False)
    return {
        "command": cmd,
        "returncode": cp.returncode,
        "stdout": cp.stdout.strip(),
        "stderr": cp.stderr.strip(),
        "ok": cp.returncode == 0,
    }


def load_usage(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cost_usd",
        "startup_context_tokens",
        "source",
    }
    return {k: data[k] for k in sorted(allowed) if k in data}


def _require_non_negative_number(data: dict[str, Any], key: str, source: Path) -> int | float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{source}: missing numeric usage field `{key}`")
    if value < 0:
        raise ValueError(f"{source}: usage field `{key}` must be non-negative")
    return value


def _require_non_empty_text(data: dict[str, Any], key: str, source: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: missing non-empty `{key}`")
    return value.strip()


def load_b0_session(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: session JSON must be an object")
    session_id = _require_non_empty_text(data, "id", path)
    if session_id not in REQUIRED_B0_SESSION_IDS:
        expected = ", ".join(REQUIRED_B0_SESSION_IDS)
        raise ValueError(f"{path}: unexpected B0 session id `{session_id}`; expected one of: {expected}")

    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError(f"{path}: missing object `usage`")
    normalized_usage: dict[str, int | float] = {
        key: _require_non_negative_number(usage, key, path) for key in REQUIRED_B0_USAGE_FIELDS
    }
    normalized_usage["cache_creation_input_tokens"] = _require_non_negative_number(
        usage, "cache_creation_input_tokens", path
    ) if "cache_creation_input_tokens" in usage else 0
    normalized_usage["total_tokens"] = (
        normalized_usage["input_tokens"]
        + normalized_usage["output_tokens"]
        + normalized_usage["cache_creation_input_tokens"]
        + normalized_usage["cache_read_input_tokens"]
    )

    quality = data.get("quality_baseline")
    if not isinstance(quality, dict):
        raise ValueError(f"{path}: missing object `quality_baseline`")
    quality_summary = _require_non_empty_text(quality, "summary", path)
    validation_commands = quality.get("validation_commands")
    if not isinstance(validation_commands, list) or not validation_commands:
        raise ValueError(f"{path}: `quality_baseline.validation_commands` must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in validation_commands):
        raise ValueError(f"{path}: every validation command must be non-empty text")
    expected_artifacts = quality.get("expected_artifacts", [])
    if not isinstance(expected_artifacts, list):
        raise ValueError(f"{path}: `quality_baseline.expected_artifacts` must be a list when present")
    if not all(isinstance(item, str) and item.strip() for item in expected_artifacts):
        raise ValueError(f"{path}: every expected artifact must be non-empty text")

    return {
        "id": session_id,
        "label": data.get("label") or session_id.replace("_", " "),
        "source": str(path),
        "usage": normalized_usage,
        "quality_baseline": {
            "summary": quality_summary,
            "validation_commands": validation_commands,
            "expected_artifacts": expected_artifacts,
        },
    }


def summarize_b0_sessions(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "startup_context_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    for session in sessions:
        usage = session["usage"]
        for key in totals:
            totals[key] += usage[key]
    count = len(sessions)
    averages = {key: totals[key] / count for key in totals}
    return {"session_count": count, "totals": totals, "averages": averages}


def build_b0_baseline(args: argparse.Namespace) -> dict[str, Any]:
    sessions = [load_b0_session(path) for path in args.session_json]
    seen = {session["id"] for session in sessions}
    required = set(REQUIRED_B0_SESSION_IDS)
    if len(sessions) != len(seen):
        raise ValueError("B0 baseline requires unique session ids")
    if seen != required:
        missing = ", ".join(sorted(required - seen)) or "none"
        extra = ", ".join(sorted(seen - required)) or "none"
        raise ValueError(f"B0 baseline requires exactly {', '.join(REQUIRED_B0_SESSION_IDS)}; missing={missing}; extra={extra}")

    sessions = sorted(sessions, key=lambda item: REQUIRED_B0_SESSION_IDS.index(item["id"]))
    data = build_probe(args)
    data["method"] = "B0"
    data["mixed_session_baseline"] = {
        "required_session_ids": list(REQUIRED_B0_SESSION_IDS),
        "summary": summarize_b0_sessions(sessions),
        "sessions": sessions,
        "quality_gate": (
            "A proxy can only pass if these same session classes produce functionally "
            "equivalent artifacts and validation gates still pass."
        ),
    }
    return data


def build_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    claude_file = args.claude_file or (Path.home() / ".claude" / "CLAUDE.md")
    codex_file = args.codex_file or (Path.home() / ".codex" / "AGENTS.md")
    cline_file = args.cline_file or (Path.home() / ".clinerules" / "agent-rules.md")
    antigravity_file = args.antigravity_file or (Path.home() / ".gemini" / "GEMINI.md")
    probe = {
        "schema_version": 1,
        "generated_at": _now(),
        "method": args.method,
        "repo_root": str(repo_root),
        "notes": args.note or "",
        "files": {
            "claude_global": kernel_presence(claude_file),
            "codex_global": kernel_presence(codex_file),
            "cline_global": kernel_presence(cline_file),
            "antigravity_global": kernel_presence(antigravity_file),
        },
        "usage": load_usage(args.usage_json),
        "sync_check": None if args.skip_sync_check else run_sync_check(repo_root),
    }
    return probe


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_baseline(args: argparse.Namespace) -> int:
    data = build_probe(args)
    write_json(args.output, data)
    print(f"wrote {args.output}")
    return 0


def cmd_mixed_baseline(args: argparse.Namespace) -> int:
    try:
        data = build_b0_baseline(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    write_json(args.output, data)
    print(f"wrote {args.output}")
    return 0


def _compare_metric(name: str, baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = baseline.get("files", {}).get(name, {})
    after = current.get("files", {}).get(name, {})
    return {
        "exists": bool(after.get("exists")),
        "kernel_ok": bool(after.get("ok")),
        "bytes_delta": after.get("bytes", 0) - before.get("bytes", 0),
        "lines_delta": after.get("lines", 0) - before.get("lines", 0),
        "sha_changed": before.get("sha256") != after.get("sha256"),
    }


def cmd_check(args: argparse.Namespace) -> int:
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = build_probe(args)
    report = {
        "schema_version": 1,
        "generated_at": _now(),
        "baseline": str(args.baseline),
        "method": current["method"],
        "files": {
            name: _compare_metric(name, baseline, current)
            for name in sorted(current.get("files", {}))
        },
        "sync_check": current["sync_check"],
    }
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))

    failures = []
    for name, metric in report["files"].items():
        if metric["exists"] and not metric["kernel_ok"]:
            failures.append(f"{name}: managed kernel missing or incomplete")
    if current["sync_check"] is not None and not current["sync_check"]["ok"]:
        failures.append("sync_agent_rules.py --check failed")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent Workflow OS session cost probe")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
        p.add_argument("--method", choices=["B0", "A1", "A2"], default="A1")
        p.add_argument("--usage-json", type=Path)
        p.add_argument("--claude-file", type=Path)
        p.add_argument("--codex-file", type=Path)
        p.add_argument("--cline-file", type=Path)
        p.add_argument("--antigravity-file", type=Path)
        p.add_argument("--skip-sync-check", action="store_true")
        p.add_argument("--note", default="")

    b = sub.add_parser("baseline", help="Write a tracked baseline JSON")
    add_common(b)
    b.add_argument("--output", type=Path, required=True)

    mb = sub.add_parser("mixed-baseline", help="Write a B0 mixed-session baseline from three measured session JSON files")
    add_common(mb)
    mb.set_defaults(method="B0")
    mb.add_argument("--output", type=Path, required=True)
    mb.add_argument(
        "--session-json",
        type=Path,
        action="append",
        required=True,
        help="Measured B0 session JSON. Provide exactly one for each required session id.",
    )

    c = sub.add_parser("check", help="Compare current probe to a baseline")
    add_common(c)
    c.add_argument("--baseline", type=Path, required=True)
    c.add_argument("--output", type=Path)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.cmd == "baseline":
        return cmd_baseline(args)
    if args.cmd == "mixed-baseline":
        return cmd_mixed_baseline(args)
    if args.cmd == "check":
        return cmd_check(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
