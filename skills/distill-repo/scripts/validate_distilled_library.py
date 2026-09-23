#!/usr/bin/env python3
"""Validate distill-repo generated skill-library artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The shared detector lives in <root>/scripts, both in the repository and in an
# installed ~/.claude (skills and scripts are siblings in each layout). A
# standalone copy of this skill without it keeps its local patterns only.
_SHARED = Path(__file__).resolve().parents[3] / "scripts"
if (_SHARED / "secret_patterns.py").is_file() and str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
try:
    from secret_patterns import find_high_confidence as _find_high_confidence
except ImportError:  # pragma: no cover - standalone copy of the skill
    _find_high_confidence = None


REQUIRED_SKILL_TERMS = (
    "description:",
    "trigger-phrases",
    "PACKET",
    "Provenance",
    "re-verification",
    "owns ",
    "defers to",
    "When not to use",
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(token|secret|password|passwd|api[_-]?key|access[_-]?key|auth[_-]?token)\b"
            r"\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{8,}"
        ),
    ),
    (
        "credential query parameter",
        re.compile(
            r"(?i)[?&](token|secret|password|passwd|api[_-]?key|access[_-]?key|auth[_-]?token)="
            r"[^&\s]{8,}"
        ),
    ),
    (
        "account assignment",
        re.compile(
            r"(?i)\b(account[_-]?(id|number)|PROJECTX_[A-Z0-9_]*|IBKR_[A-Z0-9_]*)\b"
            r"\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{4,}"
        ),
    ),
)


def _read(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8-sig")
    return text.lstrip("\ufeff").replace("\r\n", "\n")


def _has_frontmatter(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---\n", 4)
    if end == -1:
        return False
    frontmatter = text[4:end]
    return "name:" in frontmatter and "description:" in frontmatter


def _check_text_for_secrets(path: Path, text: str) -> list[str]:
    failures: list[str] = []
    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            failures.append(f"{path}: possible {label} near {match.group(1)!r}")
    # Token shapes the local list never covered (audit F14). Reported by label
    # only: echoing the match into a failure message would print the secret.
    if _find_high_confidence is not None:
        for label in _find_high_confidence(text):
            failures.append(f"{path}: {label} (high-confidence secret shape)")
    return failures


def _check_skill(path: Path) -> list[str]:
    text = _read(path)
    failures: list[str] = []
    if not _has_frontmatter(text):
        failures.append(f"{path}: missing name/description frontmatter")
    lower_text = text.lower()
    for term in REQUIRED_SKILL_TERMS:
        if term.lower() not in lower_text:
            failures.append(f"{path}: missing required term {term!r}")
    failures.extend(_check_text_for_secrets(path, text))
    return failures


def _check_agents_block(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = _read(path)
    begin = "<!-- BEGIN distill-repo skills -->"
    end = "<!-- END distill-repo skills -->"
    if begin not in text and end not in text:
        return []
    if text.count(begin) != 1 or text.count(end) != 1:
        return [f"{path}: distill-repo managed block markers must appear exactly once"]
    if text.index(begin) > text.index(end):
        return [f"{path}: distill-repo managed block markers are reversed"]
    return _check_text_for_secrets(path, text)


def _check_discovery(path: Path | None) -> list[str]:
    if path is None:
        return []
    text = _read(path)
    candidate_count = len(re.findall(r"(?im)^\s*[-*]\s+[`']?[a-z0-9][a-z0-9-]+[`']?\s*(?::|\s+-)", text))
    has_gap = "taxonomy gap" in text.lower() or "taxonomy gaps" in text.lower()
    if candidate_count < 8 and not has_gap:
        return [f"{path}: discovery must list >=8 candidates or explicit taxonomy gaps"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target_repo", type=Path)
    parser.add_argument("--discovery", type=Path, required=True)
    args = parser.parse_args()

    skills_root = args.target_repo / ".claude" / "skills"
    if not skills_root.exists():
        print(f"missing generated skills root: {skills_root}", file=sys.stderr)
        return 2

    skill_files = sorted(skills_root.glob("*/SKILL.md"))
    if not skill_files:
        print(f"no generated SKILL.md files under {skills_root}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for skill_file in skill_files:
        failures.extend(_check_skill(skill_file))
    failures.extend(_check_agents_block(args.target_repo / "AGENTS.md"))
    failures.extend(_check_discovery(args.discovery))

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    print(f"validated {len(skill_files)} generated skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
