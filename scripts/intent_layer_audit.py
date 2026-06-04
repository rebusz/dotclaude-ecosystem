#!/usr/bin/env python3
"""Audit root agent instruction files for intent-layer bloat and refs hygiene."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


BEGIN = "<!-- BEGIN AGENT-RULES:shared:v1 -->"
END = "<!-- END AGENT-RULES:shared:v1 -->"
ROOT_FILES = ("AGENTS.md", "CLAUDE.md")
DEFAULT_MAX_ROOT_LINES = 90
DEFAULT_MAX_MANUAL_LINES = 50


@dataclass
class FileAudit:
    file: str
    exists: bool
    total_lines: int = 0
    nonblank_lines: int = 0
    managed_lines: int = 0
    manual_lines: int = 0
    has_managed_block: bool = False
    refs_pointer: bool = False
    flags: list[str] | None = None

    def __post_init__(self) -> None:
        if self.flags is None:
            self.flags = []


@dataclass
class RepoAudit:
    repo: str
    refs_dir: bool
    files: list[FileAudit]
    flags: list[str]


def line_count(text: str) -> int:
    return 0 if text == "" else len(text.splitlines())


def managed_line_count(lines: Sequence[str]) -> tuple[int, bool]:
    try:
        begin = lines.index(BEGIN)
        end = lines.index(END, begin + 1)
    except ValueError:
        return 0, False
    return end - begin + 1, True


def has_refs_pointer(text: str) -> bool:
    lowered = text.lower()
    return ".claude/refs" in lowered or ".claude\\refs" in lowered


def audit_file(path: Path, max_root_lines: int, max_manual_lines: int) -> FileAudit:
    if not path.exists():
        return FileAudit(file=path.name, exists=False, flags=["missing_file"])

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = line_count(text)
    managed_lines, has_managed = managed_line_count(lines)
    audit = FileAudit(
        file=path.name,
        exists=True,
        total_lines=total,
        nonblank_lines=sum(1 for line in lines if line.strip()),
        managed_lines=managed_lines,
        manual_lines=max(0, total - managed_lines),
        has_managed_block=has_managed,
        refs_pointer=has_refs_pointer(text),
    )

    if total > max_root_lines:
        audit.flags.append("oversized_root")
    if audit.manual_lines > max_manual_lines:
        audit.flags.append("oversized_manual")
    return audit


def audit_repo(repo: Path, max_root_lines: int, max_manual_lines: int) -> RepoAudit:
    files = [audit_file(repo / name, max_root_lines, max_manual_lines) for name in ROOT_FILES]
    refs_dir = (repo / ".claude" / "refs").is_dir()
    flags: list[str] = []
    if not refs_dir:
        flags.append("missing_refs_dir")
    if refs_dir and not any(file.refs_pointer for file in files if file.exists):
        flags.append("missing_refs_pointer")
    for file in files:
        flags.extend(f"{file.file}:{flag}" for flag in file.flags or [])
    return RepoAudit(repo=str(repo), refs_dir=refs_dir, files=files, flags=flags)


def audit_repos(paths: Iterable[Path], max_root_lines: int, max_manual_lines: int) -> list[RepoAudit]:
    return [audit_repo(path.resolve(), max_root_lines, max_manual_lines) for path in paths]


def render_markdown(audits: Sequence[RepoAudit]) -> str:
    rows = [
        "| Repo | File | Lines | Manual | Managed | Refs dir | Refs pointer | Flags |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for repo in audits:
        repo_name = Path(repo.repo).name
        for file in repo.files:
            flags = ", ".join(file.flags or [])
            rows.append(
                "| {repo} | {file} | {lines} | {manual} | {managed} | {refs_dir} | {refs_pointer} | {flags} |".format(
                    repo=repo_name,
                    file=file.file,
                    lines=file.total_lines if file.exists else "MISSING",
                    manual=file.manual_lines if file.exists else "-",
                    managed=file.managed_lines if file.exists else "-",
                    refs_dir="yes" if repo.refs_dir else "no",
                    refs_pointer="yes" if file.refs_pointer else "no",
                    flags=flags or "-",
                )
            )
    repo_flags = [f"- `{Path(repo.repo).name}`: {', '.join(repo.flags) or 'clean'}" for repo in audits]
    return "\n".join(["# Intent Layer Audit", "", *rows, "", "## Repo Flags", "", *repo_flags, ""]) + "\n"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit root AGENTS.md/CLAUDE.md intent layers.")
    parser.add_argument("repos", nargs="+", help="repo roots to audit")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--max-root-lines", type=int, default=DEFAULT_MAX_ROOT_LINES)
    parser.add_argument("--max-manual-lines", type=int, default=DEFAULT_MAX_MANUAL_LINES)
    parser.add_argument("--fail-on-findings", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    audits = audit_repos(
        [Path(os.path.expanduser(repo)) for repo in args.repos],
        max_root_lines=args.max_root_lines,
        max_manual_lines=args.max_manual_lines,
    )
    if args.format == "json":
        print(json.dumps([asdict(audit) for audit in audits], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(audits), end="")
    if args.fail_on_findings and any(audit.flags for audit in audits):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
