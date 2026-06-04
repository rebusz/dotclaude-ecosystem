#!/usr/bin/env python3
"""Run noisy commands with full raw evidence and bounded chat-facing output."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_MAX_LINES = 12
DEFAULT_MAX_CHARS = 4000
TIMEOUT_EXIT_CODE = 124

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|authorization|bearer|password|passwd|secret|token)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)\b(xox[baprs]-[A-Za-z0-9-]{12,})\b"),
]

SENSITIVE_COMMAND_TOKENS = {
    "env",
    "printenv",
    "set",
}

SENSITIVE_COMMAND_PHRASES = {
    "get-childitem env:",
    "gci env:",
    "ls env:",
}


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_command(command: Sequence[str]) -> list[str]:
    return [redact_text(part) for part in command]


def sanitize_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.strip()).strip("-")
    return safe[:80] or "command"


def default_artifact_dir() -> Path:
    return Path(tempfile.gettempdir()) / "terminal-evidence"


def looks_sensitive_command(command: Sequence[str]) -> bool:
    joined = " ".join(command).strip().lower()
    base = Path(command[0]).name.lower() if command else ""
    return base in SENSITIVE_COMMAND_TOKENS or any(phrase in joined for phrase in SENSITIVE_COMMAND_PHRASES)


def split_lines(text: str) -> list[str]:
    return text.splitlines()


def bounded_lines(lines: Sequence[str], max_lines: int, max_chars: int) -> list[str]:
    selected = list(lines[-max_lines:]) if max_lines > 0 else []
    bounded: list[str] = []
    remaining = max_chars
    for line in selected:
        redacted = redact_text(line)
        if remaining <= 0:
            break
        if len(redacted) > remaining:
            bounded.append(redacted[: max(0, remaining - 3)] + "...")
            break
        bounded.append(redacted)
        remaining -= len(redacted) + 1
    return bounded


def interesting_lines(lines: Iterable[str], pattern: re.Pattern[str], limit: int = 8) -> list[str]:
    found: list[str] = []
    for line in lines:
        if is_success_test_line(line):
            continue
        if pattern.search(line):
            found.append(redact_text(line.strip()))
            if len(found) >= limit:
                break
    return found


def is_success_test_line(line: str) -> bool:
    return bool(re.search(r"\s\.\.\.\s+(ok|passed)\s*$", line, re.IGNORECASE))


def repeated_groups(lines: Iterable[str], limit: int = 5) -> list[dict[str, object]]:
    normalized: list[str] = []
    for line in lines:
        if is_success_test_line(line):
            continue
        if not re.search(r"(?i)(error|fail|failed|warning|warn|traceback|assert)", line):
            continue
        text = re.sub(r"\d+", "#", redact_text(line.strip()))
        text = re.sub(r"\s+", " ", text)
        if text:
            normalized.append(text[:220])
    return [
        {"count": count, "pattern": pattern}
        for pattern, count in Counter(normalized).most_common(limit)
        if count > 1
    ]


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def build_artifact_paths(label: str, artifact_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{sanitize_label(label)}"
    return artifact_dir / f"{base}.log", artifact_dir / f"{base}.summary.json"


def run_with_evidence(
    command: Sequence[str],
    *,
    label: str,
    risk_class: str,
    cwd: Path,
    artifact_dir: Path,
    timeout_s: float | None,
    max_lines: int,
    max_chars: int,
    allow_sensitive: bool = False,
) -> tuple[int, dict[str, object]]:
    if not command:
        raise ValueError("command is required after --")
    if looks_sensitive_command(command) and not allow_sensitive:
        summary = {
            "label": label,
            "risk_class": risk_class,
            "cwd": str(cwd),
            "command_redacted": redact_command(command),
            "exit_code": 2,
            "elapsed_s": 0.0,
            "timed_out": False,
            "summary": "refused likely environment/secret dump; pass --allow-sensitive only after redaction review",
            "failures": ["sensitive command refused"],
            "warnings": [],
            "known_unrelated": [],
            "repeated_error_groups": [],
            "artifact_path": None,
            "summary_path": None,
        }
        return 2, summary

    artifact_path, summary_path = build_artifact_paths(label, artifact_dir)
    start = time.perf_counter()
    timed_out = False
    stdout = ""
    stderr = ""
    exit_code = 0

    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = int(result.returncode)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        exit_code = TIMEOUT_EXIT_CODE

    elapsed_s = round(time.perf_counter() - start, 3)
    stdout_lines = split_lines(stdout)
    stderr_lines = split_lines(stderr)
    combined_lines = stdout_lines + stderr_lines
    failure_rx = re.compile(r"(?i)(failed|failure|error|traceback|assert|exception|timed out)")
    warning_rx = re.compile(r"(?i)(warning|warn|skipped|xfail)")
    failures = interesting_lines(combined_lines, failure_rx)
    warnings = interesting_lines(combined_lines, warning_rx)

    if timed_out:
        failures.insert(0, f"command timed out after {timeout_s}s")
    if exit_code != 0 and not failures:
        failures.append(f"process exited with code {exit_code}")

    raw = "\n".join(
        [
            f"label: {label}",
            f"risk_class: {risk_class}",
            f"cwd: {cwd}",
            f"command_redacted: {json.dumps(redact_command(command), ensure_ascii=False)}",
            f"exit_code: {exit_code}",
            f"elapsed_s: {elapsed_s}",
            f"timed_out: {str(timed_out).lower()}",
            "",
            "===== STDOUT =====",
            stdout,
            "",
            "===== STDERR =====",
            stderr,
        ]
    )
    write_atomic(artifact_path, raw)

    summary = {
        "label": label,
        "risk_class": risk_class,
        "cwd": str(cwd),
        "command_redacted": redact_command(command),
        "exit_code": exit_code,
        "elapsed_s": elapsed_s,
        "timed_out": timed_out,
        "stdout_lines": len(stdout_lines),
        "stderr_lines": len(stderr_lines),
        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "summary": f"exit={exit_code}; stdout_lines={len(stdout_lines)}; stderr_lines={len(stderr_lines)}",
        "failures": failures,
        "warnings": warnings,
        "known_unrelated": [],
        "repeated_error_groups": repeated_groups(combined_lines),
        "tail": bounded_lines(combined_lines, max_lines=max_lines, max_chars=max_chars),
        "artifact_path": str(artifact_path),
        "summary_path": str(summary_path),
    }
    write_atomic(summary_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return exit_code, summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a command, store full output, and print a bounded evidence summary.",
        epilog=(
            "Examples:\n"
            "  python terminal_evidence.py --label pytest-unit -- python -m pytest tests/test_x.py -q\n"
            "  python terminal_evidence.py --label build -- npm run build\n"
            "  python terminal_evidence.py --risk R1 --timeout 30 -- python -c \"print('ok')\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--label", default="command", help="short artifact label")
    parser.add_argument("--risk", default="R1", help="risk class label for the summary")
    parser.add_argument("--cwd", default=os.getcwd(), help="command working directory")
    parser.add_argument("--artifact-dir", default=str(default_artifact_dir()), help="raw/summary artifact directory")
    parser.add_argument("--timeout", type=float, default=None, help="timeout in seconds")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES, help="tail lines kept in summary")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="max tail characters kept in summary")
    parser.add_argument("--pretty", action="store_true", help="print indented JSON summary")
    parser.add_argument("--allow-sensitive", action="store_true", help="allow likely env/secret dump commands")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command argv, usually after --")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        code, summary = run_with_evidence(
            args.command,
            label=args.label,
            risk_class=args.risk,
            cwd=Path(args.cwd).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            timeout_s=args.timeout,
            max_lines=args.max_lines,
            max_chars=args.max_chars,
            allow_sensitive=args.allow_sensitive,
        )
    except Exception as exc:
        print(json.dumps({"exit_code": 2, "failures": [str(exc)]}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
