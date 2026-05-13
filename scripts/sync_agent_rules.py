#!/usr/bin/env python3
"""Synchronize managed Claude/Codex instruction blocks from agent-rules sources.

The script is intentionally conservative:
- source files are read from a git-tracked source tree
- only versioned AGENT-RULES managed blocks are edited
- malformed markers fail closed
- writes are lock-protected and atomic

Default source root:
    D:/dotclaude/dotclaude-ecosystem/agent-rules
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

BEGIN = "<!-- BEGIN AGENT-RULES:shared:v1 -->"
END = "<!-- END AGENT-RULES:shared:v1 -->"
DEFAULT_SOURCE_ROOT = Path("D:/dotclaude/dotclaude-ecosystem/agent-rules")
TSIGNAL_REPO = Path("D:/APPS/Tsignal 5.0")
LOCK_TIMEOUT_S = 10.0


class SyncError(RuntimeError):
    """Fatal sync error."""


class DriftError(SyncError):
    """Target has drift or is missing a managed block."""


@dataclass(frozen=True)
class TargetSpec:
    name: str
    path: Path
    sources: tuple[Path, ...]
    line_limit: int | None = None
    byte_limit: int | None = None


@dataclass
class TargetResult:
    spec: TargetSpec
    changed: bool
    backup_path: Path | None = None
    checksum: str = ""
    message: str = ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SyncError(f"{path}: not valid UTF-8") from exc
    except OSError as exc:
        raise SyncError(f"{path}: cannot read ({exc})") from exc


def _write_atomic(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.gettempdir()) / "agent-rules-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{path.name}.{stamp}.bak"
    if path.exists():
        shutil.copy2(path, backup)
    else:
        backup.write_text("", encoding="utf-8")

    tmp_path = path.parent / f".{path.name}.agent-rules.tmp"
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp_path, path)
    return backup


def _acquire_lock(path: Path) -> Path:
    lock_path = path.parent / f".{path.name}.agent-rules.lock"
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()}\n")
            return lock_path
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise SyncError(f"{path}: lock timeout at {lock_path}")
            time.sleep(0.1)


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _source_digest(parts: list[tuple[Path, str]]) -> str:
    h = hashlib.sha256()
    for rel, text in parts:
        h.update(str(rel).replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def render_block(source_root: Path, sources: tuple[Path, ...]) -> tuple[str, str]:
    parts: list[tuple[Path, str]] = []
    for rel in sources:
        source_path = source_root / rel
        if not source_path.exists():
            raise SyncError(f"missing source file: {source_path}")
        text = _read_text(source_path).strip()
        if not text:
            raise SyncError(f"empty source file: {source_path}")
        parts.append((rel, text))

    checksum = _source_digest(parts)
    body: list[str] = [
        f"<!-- Managed by sync_agent_rules.py; checksum={checksum} -->",
        "",
    ]
    for rel, text in parts:
        body.append(f"<!-- Source: {str(rel).replace(chr(92), '/')} -->")
        body.append(text)
        body.append("")
    return "\n".join(body).rstrip() + "\n", checksum


def find_managed_block(text: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    begin_indexes: list[int] = []
    end_indexes: list[int] = []
    in_fence = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if stripped in {BEGIN, END} and in_fence:
            raise SyncError(f"managed marker appears inside code fence at line {idx + 1}")
        if stripped == BEGIN:
            begin_indexes.append(idx)
        elif stripped == END:
            end_indexes.append(idx)

    if not begin_indexes and not end_indexes:
        return None
    if len(begin_indexes) != 1 or len(end_indexes) != 1:
        raise SyncError(
            f"managed marker count invalid: begin={len(begin_indexes)} end={len(end_indexes)}"
        )
    begin = begin_indexes[0]
    end = end_indexes[0]
    if begin >= end:
        raise SyncError(f"managed marker order invalid: begin line {begin + 1}, end line {end + 1}")
    return begin, end


def replace_or_insert_block(existing: str, rendered: str, init: bool) -> str:
    normalized = existing.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    block = find_managed_block(normalized)
    rendered_lines = [BEGIN, *rendered.rstrip("\n").splitlines(), END]

    if block is None:
        if not init:
            raise DriftError("managed block missing; rerun with --init-managed-blocks")
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        new_lines = lines[:insert_at] + [""] + rendered_lines + [""] + lines[insert_at:]
    else:
        begin, end = block
        new_lines = lines[: begin + 1] + rendered.rstrip("\n").splitlines() + lines[end:]

    return "\n".join(new_lines).rstrip() + "\n"


def validate_constraints(spec: TargetSpec, text: str) -> None:
    if spec.line_limit is not None:
        line_count = len(text.splitlines())
        if line_count > spec.line_limit:
            raise SyncError(f"{spec.path}: {line_count} lines exceeds limit {spec.line_limit}")
    if spec.byte_limit is not None:
        byte_count = len(text.encode("utf-8"))
        if byte_count > spec.byte_limit:
            raise SyncError(f"{spec.path}: {byte_count} bytes exceeds limit {spec.byte_limit}")


def target_specs(source_root: Path, repo: Path | None) -> list[TargetSpec]:
    home = Path.home()
    specs = [
        TargetSpec(
            name="claude-global",
            path=home / ".claude" / "CLAUDE.md",
            sources=(Path("core.md"), Path("overlays/claude-global.md")),
            line_limit=200,
        ),
        TargetSpec(
            name="codex-global",
            path=home / ".codex" / "AGENTS.md",
            sources=(Path("core.md"), Path("overlays/codex-global.md")),
            byte_limit=32 * 1024,
        ),
    ]

    if repo is not None:
        resolved = repo.resolve()
        if resolved != TSIGNAL_REPO.resolve():
            raise SyncError(f"repo is not allowlisted for pilot sync: {repo}")
        specs.extend(
            [
                TargetSpec(
                    name="tsignal-claude",
                    path=resolved / "CLAUDE.md",
                    sources=(
                        Path("repos/tsignal-5.0/shared.md"),
                        Path("repos/tsignal-5.0/claude.md"),
                    ),
                ),
                TargetSpec(
                    name="tsignal-codex",
                    path=resolved / "AGENTS.md",
                    sources=(
                        Path("repos/tsignal-5.0/shared.md"),
                        Path("repos/tsignal-5.0/codex.md"),
                    ),
                    byte_limit=32 * 1024,
                ),
            ]
        )
    return specs


def sync_target(
    spec: TargetSpec,
    source_root: Path,
    *,
    init: bool,
    write: bool,
    show_diff: bool,
) -> TargetResult:
    rendered, checksum = render_block(source_root, spec.sources)
    existing = _read_text(spec.path) if spec.path.exists() else ""
    new_text = replace_or_insert_block(existing, rendered, init=init)
    validate_constraints(spec, new_text)
    changed = existing.replace("\r\n", "\n").replace("\r", "\n").rstrip() != new_text.rstrip()

    if show_diff and changed:
        diff = difflib.unified_diff(
            existing.splitlines(),
            new_text.splitlines(),
            fromfile=str(spec.path),
            tofile=f"{spec.path} (agent-rules)",
            lineterm="",
        )
        print("\n".join(diff))

    backup = None
    if write and changed:
        lock_path = _acquire_lock(spec.path)
        try:
            # Re-read while holding the lock so concurrent edits are not lost.
            locked_existing = _read_text(spec.path) if spec.path.exists() else ""
            locked_new = replace_or_insert_block(locked_existing, rendered, init=init)
            validate_constraints(spec, locked_new)
            backup = _write_atomic(spec.path, locked_new)
        finally:
            _release_lock(lock_path)

    status = "changed" if changed else "clean"
    return TargetResult(spec=spec, changed=changed, backup_path=backup, checksum=checksum, message=status)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync managed Claude/Codex instruction blocks.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Check drift without writing (default)")
    action.add_argument("--diff", action="store_true", help="Print unified diff without writing")
    action.add_argument("--write", action="store_true", help="Write managed blocks")
    parser.add_argument("--init-managed-blocks", action="store_true", help="Insert missing managed blocks")
    parser.add_argument("--repo", type=Path, default=None, help="Pilot repo path to include")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Optional target name filter; can be repeated",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    source_root = args.source_root.resolve()
    write = bool(args.write)
    show_diff = bool(args.diff)

    try:
        specs = target_specs(source_root, args.repo)
        if args.target:
            wanted = set(args.target)
            specs = [spec for spec in specs if spec.name in wanted]
            missing = wanted - {spec.name for spec in specs}
            if missing:
                raise SyncError(f"unknown target filter(s): {', '.join(sorted(missing))}")
        if not specs:
            raise SyncError("no targets selected")

        results: list[TargetResult] = []
        for spec in specs:
            results.append(
                sync_target(
                    spec,
                    source_root,
                    init=args.init_managed_blocks,
                    write=write,
                    show_diff=show_diff,
                )
            )

        if not args.quiet:
            for result in results:
                backup = f" backup={result.backup_path}" if result.backup_path else ""
                print(
                    f"{result.spec.name}: {result.message} checksum={result.checksum} "
                    f"path={result.spec.path}{backup}"
                )

        changed = any(result.changed for result in results)
        return 0 if write or not changed else 2
    except DriftError as exc:
        print(f"DRIFT: {exc}", file=sys.stderr)
        return 2
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
