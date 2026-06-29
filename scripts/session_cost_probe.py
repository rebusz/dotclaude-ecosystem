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


def build_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    claude_file = args.claude_file or (Path.home() / ".claude" / "CLAUDE.md")
    codex_file = args.codex_file or (Path.home() / ".codex" / "AGENTS.md")
    probe = {
        "schema_version": 1,
        "generated_at": _now(),
        "method": args.method,
        "repo_root": str(repo_root),
        "notes": args.note or "",
        "files": {
            "claude_global": kernel_presence(claude_file),
            "codex_global": kernel_presence(codex_file),
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
            "claude_global": _compare_metric("claude_global", baseline, current),
            "codex_global": _compare_metric("codex_global", baseline, current),
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
        p.add_argument("--skip-sync-check", action="store_true")
        p.add_argument("--note", default="")

    b = sub.add_parser("baseline", help="Write a tracked baseline JSON")
    add_common(b)
    b.add_argument("--output", type=Path, required=True)

    c = sub.add_parser("check", help="Compare current probe to a baseline")
    add_common(c)
    c.add_argument("--baseline", type=Path, required=True)
    c.add_argument("--output", type=Path)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.cmd == "baseline":
        return cmd_baseline(args)
    if args.cmd == "check":
        return cmd_check(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
