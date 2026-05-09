#!/usr/bin/env python3
"""Global Plan Catalog — generates ~/.claude/PLANS.md.

Scans all repos under d:/APPS/*/design/plans/ and design/audits/.
Run: python ~/.claude/scripts/plan_catalog.py [--verbose]
"""

import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from _catalog_common import discover_repos, walk_repos, parse_yaml_block

OUTPUT = Path.home() / ".claude" / "PLANS.md"
BASE = "d:/APPS"

VALID_STATUSES = frozenset(["draft", "in-progress", "shipped", "abandoned", "blocked", "unknown"])
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BODY_DATE_RE = re.compile(r"^\*\*Date\*\*:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_INLINE_RE = re.compile(r"[*_`]")


class PlanEntry(TypedDict):
    path: str
    repo: str
    title: str
    date: str
    status: str
    repos: list[str]
    tags: list[str]
    risk: str
    phase: str
    related: list[str]
    has_frontmatter: bool
    is_audit: bool


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "-")


def _strip_md(text: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", text)
    return _MD_INLINE_RE.sub("", text).strip()


def _date_from_filename(path: Path) -> str:
    m = _DATE_RE.search(path.stem)
    return m.group() if m else ""


def _date_from_body(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        m = _BODY_DATE_RE.search(text)
        return m.group(1) if m else ""
    except OSError:
        return ""


def _date_from_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return date.today().isoformat()


def _h1_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        m = _H1_RE.search(text)
        return _strip_md(m.group(1)) if m else ""
    except OSError:
        return ""


def _file_uri(path: Path) -> str:
    posix = path.as_posix()
    # Windows: d:/APPS/... → file:///d:/APPS/...
    encoded = posix.replace(" ", "%20")
    if len(encoded) > 1 and encoded[1] == ":":
        return f"file:///{encoded}"
    return f"file:///{encoded}"


def parse_plan_frontmatter(path: Path) -> PlanEntry:
    is_audit = "design/audits" in path.as_posix()
    repo_dir = path
    for _ in range(5):
        repo_dir = repo_dir.parent
        if (repo_dir / "design").exists() or repo_dir == repo_dir.parent:
            break
    repo = _slugify(repo_dir.name)

    raw = parse_yaml_block(path)
    has_fm = bool(raw)

    title = raw.get("title", "") or _h1_title(path) or _slugify(path.stem)
    title = _strip_md(str(title))

    date_str = str(raw.get("date", ""))
    if not _DATE_RE.fullmatch(date_str):
        date_str = _date_from_filename(path) or _date_from_body(path) or _date_from_mtime(path)

    raw_status = str(raw.get("status", "")).strip().lower()
    status = raw_status if raw_status in VALID_STATUSES else "unknown"
    if raw_status and raw_status not in VALID_STATUSES:
        logging.warning("plan_catalog: %s has invalid status %r, using 'unknown'", path.name, raw_status)

    repos_raw = raw.get("repos", [])
    if isinstance(repos_raw, list):
        repos = [_slugify(r) for r in repos_raw if r]
    else:
        repos = [_slugify(str(repos_raw))] if repos_raw else [repo]

    tags = raw.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    related = raw.get("related", [])
    if not isinstance(related, list):
        related = []

    return PlanEntry(
        path=path.as_posix(),
        repo=repo,
        title=title,
        date=date_str,
        status=status,
        repos=repos,
        tags=tags,
        risk=str(raw.get("risk", "")),
        phase=str(raw.get("phase", "")),
        related=related,
        has_frontmatter=has_fm,
        is_audit=is_audit,
    )


def _find_audit_entry(audit_dir: Path) -> Path | None:
    for candidate in ("report.md", "README.md"):
        p = audit_dir / candidate
        if p.exists():
            return p
    mds = sorted(audit_dir.glob("*.md"))
    return mds[0] if mds else None


def _render_entry(e: PlanEntry) -> str:
    path = Path(e["path"])
    uri = _file_uri(path)
    repos_tag = f" — repos: {e['repos']}" if len(e["repos"]) > 1 else ""
    return f"- [{e['title']}]({uri}) — `{e['status']}`{repos_tag} — {e['date']}"


def _render_section(title: str, entries: list[PlanEntry]) -> str:
    if not entries:
        return f"## {title}\n\n(empty)\n"
    lines = [f"## {title}\n"]
    by_repo: dict[str, list[PlanEntry]] = {}
    for e in entries:
        by_repo.setdefault(e["repo"], []).append(e)
    for repo in sorted(by_repo):
        lines.append(f"### {repo}")
        for e in sorted(by_repo[repo], key=lambda x: x["date"], reverse=True):
            lines.append(_render_entry(e))
        lines.append("")
    return "\n".join(lines)


def generate(verbose: bool = False) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        repos = discover_repos(BASE)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"[plan_catalog] discovered {len(repos)} repos:", file=sys.stderr)
        for r in repos:
            print(f"  {r}", file=sys.stderr)

    md_files = walk_repos(repos)
    entries: list[PlanEntry] = []
    warnings = 0

    for f in md_files:
        try:
            e = parse_plan_frontmatter(f)
            entries.append(e)
        except Exception as exc:
            logging.warning("plan_catalog: skipping %s: %s", f, exc)
            warnings += 1

    plans = [e for e in entries if not e["is_audit"]]
    audits = [e for e in entries if e["is_audit"]]

    thirty_ago = (date.today() - timedelta(days=30)).isoformat()

    cross_repo = sorted(
        [e for e in plans if len(e["repos"]) > 1],
        key=lambda x: x["date"], reverse=True,
    )
    in_progress = [e for e in plans if e["status"] == "in-progress" and len(e["repos"]) <= 1]
    drafts = [e for e in plans if e["status"] == "draft"]
    shipped = [e for e in plans if e["status"] == "shipped" and e["date"] >= thirty_ago]
    abandoned = [e for e in plans if e["status"] in ("abandoned", "blocked")]
    unknown = [e for e in plans if e["status"] == "unknown"]

    lines: list[str] = [f"# Plan Catalog (auto-generated {now})\n"]

    if cross_repo:
        lines.append("## Cross-repo Plans (repos.length > 1)\n")
        for e in cross_repo:
            lines.append(_render_entry(e))
        lines.append("")

    lines.append(_render_section("In Progress", in_progress))
    lines.append(_render_section("Draft", drafts))
    lines.append(_render_section("Recently Shipped (last 30d)", shipped))
    lines.append(_render_section("Abandoned / Blocked", abandoned))

    lines.append("## Audits\n")
    if audits:
        by_repo: dict[str, list[PlanEntry]] = {}
        for e in audits:
            by_repo.setdefault(e["repo"], []).append(e)
        for repo in sorted(by_repo):
            lines.append(f"### {repo}")
            for e in sorted(by_repo[repo], key=lambda x: x["date"], reverse=True):
                lines.append(_render_entry(e))
            lines.append("")
    else:
        lines.append("(empty)\n")

    lines.append(_render_section("Status: unknown", unknown))

    n_repos = len(repos)
    n_plans = len(plans)
    n_audits = len(audits)
    n_inprog = sum(1 for e in plans if e["status"] == "in-progress")
    n_draft = sum(1 for e in plans if e["status"] == "draft")
    n_shipped_total = sum(1 for e in plans if e["status"] == "shipped")
    n_abandoned = len(abandoned)
    n_unknown = len(unknown)
    n_cross = len(cross_repo)

    lines.append("## Stats\n")
    lines.append(f"- {n_plans} plans, {n_audits} audits across {n_repos} repos")
    lines.append(
        f"- {n_inprog} in-progress, {n_draft} draft, {n_shipped_total} shipped, "
        f"{n_abandoned} abandoned, {n_unknown} unknown"
    )
    lines.append(f"- {n_cross} cross-repo plan(s)")
    lines.append(f"- Generator: ~/.claude/scripts/plan_catalog.py | Last run: {now}")

    content = "\n".join(lines) + "\n"
    print(
        f"[plan_catalog] scanned {n_repos} repos | {n_plans} plans | {n_audits} audits "
        f"| {warnings} warnings | wrote {OUTPUT}",
        file=sys.stderr,
    )
    return content


def write_output(path: Path, content: str) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main() -> None:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    content = generate(verbose=verbose)
    write_output(OUTPUT, content)


if __name__ == "__main__":
    main()
