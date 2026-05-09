#!/usr/bin/env python3
"""Shared helpers for plan_catalog.py and idea_digest.py.

Provides: discover_repos(), EXCLUSIONS, walk_repos(), parse_yaml_block().
Does NOT export PlanEntry or any plan-specific schema — those stay in plan_catalog.py.
"""

import logging
import os
import re
from pathlib import Path

EXCLUSIONS = frozenset([
    ".claude/worktrees",
    ".tmp-designs",
    ".cline",
    "Older",
    "Saved",
    "_scripts",
    "node_modules",
    ".git",
])

_KEY_RE = re.compile(r"^([a-z_]+):\s*(.*)$")


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUSIONS)


def discover_repos(base: str = "d:/APPS") -> list[Path]:
    """Glob base/*/design/plans/ and base/*/design/audits/ to find repo roots.

    Returns alphabetically sorted list of unique repo roots. New repos with
    design/plans/ auto-appear without code changes.
    """
    base_path = Path(base)
    if not base_path.exists():
        raise FileNotFoundError(f"Base directory not found: {base}")

    roots: set[Path] = set()
    for pattern in ("*/design/plans", "*/design/audits"):
        for match in base_path.glob(pattern):
            if match.is_dir() and not _is_excluded(match):
                roots.add(match.parent.parent)

    return sorted(roots, key=lambda p: p.name.lower())


def walk_repos(repos: list[Path]) -> list[Path]:
    """Walk repos, yielding .md files from design/plans/ and design/audits/.

    Skips missing repos, permission errors, and excluded paths.
    Returns list of .md file paths.
    """
    results: list[Path] = []
    for repo in repos:
        for subdir in ("design/plans", "design/audits"):
            target = repo / subdir
            if not target.exists():
                continue
            try:
                for root, dirs, files in os.walk(target, followlinks=False):
                    root_path = Path(root)
                    if _is_excluded(root_path):
                        dirs.clear()
                        continue
                    dirs[:] = [
                        d for d in dirs
                        if not _is_excluded(root_path / d)
                    ]
                    for fname in files:
                        if fname.endswith(".md"):
                            results.append(root_path / fname)
            except PermissionError as exc:
                logging.warning("plan_catalog: permission denied scanning %s: %s", target, exc)
    return results


def _parse_inline_list(value: str) -> list[str]:
    """Parse `[a, b, c]` inline list. Returns [] if not list syntax."""
    s = value.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return []
    inner = s[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip().strip("\"'") for p in inner.split(",")]
    return [p for p in parts if p]


def parse_yaml_block(file_path: Path) -> dict:
    """Read YAML frontmatter block line-by-line (memory-safe, 100-content-line cap).

    Returns raw dict of key→value/list. Returns {} if no frontmatter or empty block.
    Regex uses .* (not .+) so empty values like `phase: ` are accepted.
    """
    lines: list[str] = []
    try:
        with file_path.open(encoding="utf-8-sig") as f:
            first = f.readline()
            if first.strip() != "---":
                return {}
            for i, line in enumerate(f):
                if line.strip() == "---":
                    break
                if i >= 100:
                    logging.warning(
                        "plan_catalog: %s has no closing --- within 100 content lines",
                        file_path,
                    )
                    return {}
                lines.append(line.rstrip("\r\n"))
    except UnicodeDecodeError:
        logging.warning("plan_catalog: encoding error reading %s, skipping", file_path)
        return {}

    result: dict = {}
    for line in lines:
        m = _KEY_RE.match(line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("["):
            result[key] = _parse_inline_list(raw)
        elif raw.startswith('"') and raw.endswith('"'):
            result[key] = raw[1:-1]
        elif raw.startswith("'") and raw.endswith("'"):
            result[key] = raw[1:-1]
        else:
            result[key] = raw

    return result
