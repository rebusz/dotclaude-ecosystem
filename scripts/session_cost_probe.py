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
    return load_b0_session_from_object(data, path)


def load_b0_session_from_object(data: dict[str, Any], source: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: session JSON must be an object")
    session_id = _require_non_empty_text(data, "id", source)
    if session_id not in REQUIRED_B0_SESSION_IDS:
        expected = ", ".join(REQUIRED_B0_SESSION_IDS)
        raise ValueError(f"{source}: unexpected B0 session id `{session_id}`; expected one of: {expected}")

    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError(f"{source}: missing object `usage`")
    normalized_usage: dict[str, int | float] = {
        key: _require_non_negative_number(usage, key, source) for key in REQUIRED_B0_USAGE_FIELDS
    }
    normalized_usage["cache_creation_input_tokens"] = _require_non_negative_number(
        usage, "cache_creation_input_tokens", source
    ) if "cache_creation_input_tokens" in usage else 0
    normalized_usage["total_tokens"] = (
        normalized_usage["input_tokens"]
        + normalized_usage["output_tokens"]
        + normalized_usage["cache_creation_input_tokens"]
        + normalized_usage["cache_read_input_tokens"]
    )

    quality = data.get("quality_baseline")
    if not isinstance(quality, dict):
        raise ValueError(f"{source}: missing object `quality_baseline`")
    quality_summary = _require_non_empty_text(quality, "summary", source)
    validation_commands = quality.get("validation_commands")
    if not isinstance(validation_commands, list) or not validation_commands:
        raise ValueError(f"{source}: `quality_baseline.validation_commands` must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in validation_commands):
        raise ValueError(f"{source}: every validation command must be non-empty text")
    expected_artifacts = quality.get("expected_artifacts", [])
    if not isinstance(expected_artifacts, list):
        raise ValueError(f"{source}: `quality_baseline.expected_artifacts` must be a list when present")
    if not all(isinstance(item, str) and item.strip() for item in expected_artifacts):
        raise ValueError(f"{source}: every expected artifact must be non-empty text")

    return {
        "id": session_id,
        "label": data.get("label") or session_id.replace("_", " "),
        "source": str(source),
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


def parse_claude_jsonl_usage(path: Path) -> dict[str, Any]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    models: set[str] = set()
    assistant_messages = 0
    usage_messages = 0
    first_timestamp = None
    last_timestamp = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = item.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            assistant_messages += 1
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            usage_messages += 1
            timestamp = item.get("timestamp")
            if isinstance(timestamp, str):
                first_timestamp = first_timestamp or timestamp
                last_timestamp = timestamp
            model = message.get("model")
            if isinstance(model, str) and model:
                models.add(model)
            for key in totals:
                value = usage.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if value > 0:
                    totals[key] += value

    total_tokens = sum(totals.values())
    return {
        "source": str(path),
        "assistant_messages": assistant_messages,
        "usage_messages": usage_messages,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "models": sorted(models),
        "usage": {**totals, "total_tokens": total_tokens},
    }


def build_jsonl_inventory(directory: Path, *, limit: int, min_usage_messages: int) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    if min_usage_messages < 0:
        raise ValueError("--min-usage-messages must be non-negative")
    if not directory.exists():
        raise ValueError(f"{directory}: directory does not exist")
    if not directory.is_dir():
        raise ValueError(f"{directory}: not a directory")

    sessions: list[dict[str, Any]] = []
    for path in directory.glob("*.jsonl"):
        summary = parse_claude_jsonl_usage(path)
        if summary["usage_messages"] < min_usage_messages:
            continue
        sessions.append(
            {
                "jsonl": str(path),
                "filename": path.name,
                "bytes": path.stat().st_size,
                "assistant_messages": summary["assistant_messages"],
                "usage_messages": summary["usage_messages"],
                "first_timestamp": summary["first_timestamp"],
                "last_timestamp": summary["last_timestamp"],
                "models": summary["models"],
                "usage": summary["usage"],
            }
        )

    sessions.sort(
        key=lambda item: (
            item["usage"]["total_tokens"],
            item["usage_messages"],
            item["bytes"],
            item["filename"],
        ),
        reverse=True,
    )
    return {
        "source_dir": str(directory),
        "session_count": len(sessions),
        "returned_count": min(len(sessions), limit),
        "sort": "total_tokens_desc",
        "redaction": "prompt_content_omitted",
        "sessions": sessions[:limit],
    }


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


def build_b0_status(args: argparse.Namespace) -> dict[str, Any]:
    baseline = args.baseline
    status: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": _now(),
        "baseline": str(baseline),
        "ready": False,
        "required_session_ids": list(REQUIRED_B0_SESSION_IDS),
        "errors": [],
    }
    if not baseline.exists():
        status["errors"].append(f"missing baseline artifact: {baseline}")
        return status
    try:
        data = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        status["errors"].append(f"unable to read baseline JSON: {exc}")
        return status

    if data.get("method") != "B0":
        status["errors"].append("baseline method must be B0")
    mixed = data.get("mixed_session_baseline")
    if not isinstance(mixed, dict):
        status["errors"].append("missing object `mixed_session_baseline`")
        sessions = []
    else:
        sessions = mixed.get("sessions")
        if not isinstance(sessions, list):
            status["errors"].append("mixed_session_baseline.sessions must be a list")
            sessions = []

    valid_sessions = []
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            status["errors"].append(f"mixed_session_baseline.sessions[{index}] must be an object")
            continue
        try:
            valid_sessions.append(load_b0_session_from_object(session, baseline))
        except ValueError as exc:
            status["errors"].append(str(exc))

    seen = {session["id"] for session in valid_sessions}
    required = set(REQUIRED_B0_SESSION_IDS)
    missing = sorted(required - seen)
    extra = sorted(seen - required)
    if missing:
        status["errors"].append(f"missing required session ids: {', '.join(missing)}")
    if extra:
        status["errors"].append(f"unexpected session ids: {', '.join(extra)}")
    if len(valid_sessions) != len(seen):
        status["errors"].append("duplicate session ids present")

    status["session_ids"] = sorted(seen)
    status["ready"] = not status["errors"]
    return status


def build_b0_session_from_jsonl(args: argparse.Namespace) -> dict[str, Any]:
    if args.cost_usd < 0:
        raise ValueError("--cost-usd must be non-negative")
    if args.startup_context_tokens < 0:
        raise ValueError("--startup-context-tokens must be non-negative")
    if not args.validation_command:
        raise ValueError("--validation-command is required at least once")

    summary = parse_claude_jsonl_usage(args.jsonl)
    if summary["usage_messages"] == 0:
        raise ValueError(f"{args.jsonl}: no assistant usage records found")
    usage = {
        "input_tokens": summary["usage"]["input_tokens"],
        "output_tokens": summary["usage"]["output_tokens"],
        "cache_creation_input_tokens": summary["usage"]["cache_creation_input_tokens"],
        "cache_read_input_tokens": summary["usage"]["cache_read_input_tokens"],
        "cost_usd": args.cost_usd,
        "startup_context_tokens": args.startup_context_tokens,
    }
    return {
        "id": args.session_id,
        "label": args.label or args.session_id.replace("_", " "),
        "source_jsonl": str(args.jsonl),
        "usage_source": "claude-jsonl-plus-explicit-cost",
        "usage_record_count": summary["usage_messages"],
        "time_range": {
            "first_timestamp": summary["first_timestamp"],
            "last_timestamp": summary["last_timestamp"],
        },
        "models": summary["models"],
        "usage": usage,
        "quality_baseline": {
            "summary": args.quality_summary,
            "validation_commands": args.validation_command,
            "expected_artifacts": args.expected_artifact or [],
        },
    }


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


def cmd_jsonl_summary(args: argparse.Namespace) -> int:
    data = parse_claude_jsonl_usage(args.jsonl)
    if args.output:
        write_json(args.output, data)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def cmd_jsonl_inventory(args: argparse.Namespace) -> int:
    try:
        data = build_jsonl_inventory(
            args.dir,
            limit=args.limit,
            min_usage_messages=args.min_usage_messages,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.output:
        write_json(args.output, data)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def cmd_jsonl_session(args: argparse.Namespace) -> int:
    try:
        data = build_b0_session_from_jsonl(args)
        load_b0_session_from_object(data, Path("<generated-jsonl-session>"))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    write_json(args.output, data)
    print(f"wrote {args.output}")
    return 0


def cmd_b0_status(args: argparse.Namespace) -> int:
    data = build_b0_status(args)
    if args.output:
        write_json(args.output, data)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0 if data["ready"] else 1


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

    js = sub.add_parser("jsonl-summary", help="Summarize Claude JSONL usage without reading prompt text")
    js.add_argument("--jsonl", type=Path, required=True)
    js.add_argument("--output", type=Path)

    ji = sub.add_parser("jsonl-inventory", help="List Claude JSONL usage candidates without reading prompt text")
    ji.add_argument("--dir", type=Path, required=True)
    ji.add_argument("--limit", type=int, default=20)
    ji.add_argument("--min-usage-messages", type=int, default=1)
    ji.add_argument("--output", type=Path)

    bs = sub.add_parser("jsonl-session", help="Build one measured B0 session JSON from Claude JSONL plus explicit /cost")
    bs.add_argument("--jsonl", type=Path, required=True)
    bs.add_argument("--output", type=Path, required=True)
    bs.add_argument("--session-id", choices=REQUIRED_B0_SESSION_IDS, required=True)
    bs.add_argument("--label", default="")
    bs.add_argument("--cost-usd", type=float, required=True)
    bs.add_argument("--startup-context-tokens", type=int, required=True)
    bs.add_argument("--quality-summary", required=True)
    bs.add_argument("--validation-command", action="append", required=True)
    bs.add_argument("--expected-artifact", action="append", default=[])

    b0 = sub.add_parser("b0-status", help="Fail closed unless the B0 mixed-session baseline is complete")
    b0.add_argument(
        "--baseline",
        type=Path,
        default=Path("design/baselines/workflow_os_b0_mixed_sessions.json"),
    )
    b0.add_argument("--output", type=Path)

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
    if args.cmd == "jsonl-summary":
        return cmd_jsonl_summary(args)
    if args.cmd == "jsonl-inventory":
        return cmd_jsonl_inventory(args)
    if args.cmd == "jsonl-session":
        return cmd_jsonl_session(args)
    if args.cmd == "b0-status":
        return cmd_b0_status(args)
    if args.cmd == "check":
        return cmd_check(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
