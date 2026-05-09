#!/usr/bin/env python3
"""Pre-step loader for plan-creating modes/skills.

Reads vision (if plan attached), repo IDEA_BOX, and global PLANS.md, then emits
a compact markdown context block for AI to inject into reasoning.

Usage:
    python plan_context_loader.py --cwd "d:/APPS/Tsignal 5.0"
    python plan_context_loader.py --cwd "d:/APPS/Tsignal 5.0" --plan design/plans/2026-05-09_foo.md
    python plan_context_loader.py --repo tsignal-5

Output format: markdown sections wrapped in <plan-context>...</plan-context>.
Best-effort: never raises; missing files emit `_(none)_` lines.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home() / ".claude"
BASE = Path("d:/APPS")
VISION_INDEX = HOME / ".vision_index.json"
PLANS_CATALOG = HOME / "PLANS.md"
ECOSYSTEM_BOX = HOME / "ECOSYSTEM_IDEA_BOX.md"
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _read_text(p: Path, limit_lines: int | None = None) -> str:
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        if limit_lines:
            return "\n".join(text.splitlines()[:limit_lines])
        return text
    except Exception:
        return ""


def _detect_repo(cwd: Path) -> Path | None:
    """Walk up from cwd to find repo root under d:/APPS."""
    cwd = cwd.resolve()
    for parent in [cwd, *cwd.parents]:
        if parent.parent.resolve() == BASE.resolve():
            return parent
    return None


def _slugify_repo(name: str) -> str:
    """Match vision_catalog._slugify behavior: strip non-alnum → dash."""
    raw = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", raw) or "untitled"


def _repo_slug_variants(repo_root: Path) -> list[str]:
    """Return both vision-style slug and path-style slug for matching."""
    name = repo_root.name
    vision_slug = _slugify_repo(name)
    path_slug = name.lower().replace(" ", "-")
    return list(dict.fromkeys([vision_slug, path_slug]))


def _parse_plan_vision(plan_path: Path) -> str | None:
    """Extract `vision: <slug>` from plan frontmatter."""
    if not plan_path.exists():
        return None
    text = _read_text(plan_path, limit_lines=40)
    if not text.startswith("---"):
        return None
    in_block = False
    for line in text.splitlines():
        if line.strip() == "---":
            if in_block:
                break
            in_block = True
            continue
        if in_block and line.startswith("vision:"):
            slug = line.split(":", 1)[1].strip().strip("\"'")
            if SLUG_RE.fullmatch(slug):
                return slug
    return None


def _load_vision_index() -> dict:
    if not VISION_INDEX.exists():
        try:
            subprocess.run(
                ["python", str(HOME / "scripts" / "vision_catalog.py")],
                capture_output=True, timeout=15,
            )
        except Exception:
            return {}
    try:
        return json.loads(VISION_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _section_vision(plan: Path | None, repo_slugs: list[str], repo_root: Path) -> str:
    out = ["## Wizja powiązana"]
    index = _load_vision_index()
    visions = index.get("visions", {})

    slug = _parse_plan_vision(plan) if plan else None
    if not slug:
        repo_root_norm = repo_root.resolve().as_posix().lower()
        repo_visions = []
        for s, v in visions.items():
            vpath = (v.get("path") or "").replace("\\", "/").lower()
            if vpath.startswith(repo_root_norm):
                repo_visions.append((s, v))
                continue
            if any(rs in (v.get("repos") or []) for rs in repo_slugs):
                repo_visions.append((s, v))
                continue
            if v.get("primary_repo") in repo_slugs:
                repo_visions.append((s, v))
        if not repo_visions:
            out.append(f"_(brak wizji w tym repo {repo_slugs} — rozważ /vision new)_")
            return "\n".join(out)
        out.append(f"_Plan nie ma frontmatter `vision:`. Wizje dostępne dla repo `{repo_slugs[0]}`:_")
        for s, v in repo_visions[:5]:
            status = v.get("status", "?")
            title = v.get("title", s)
            out.append(f"- `{s}` — {title} ({status})")
        out.append("\n→ Po wyborze: dodaj `vision: <slug>` do frontmatter planu, lub `python ~/.claude/scripts/vision.py attach <plan-path> <slug>`.")
        return "\n".join(out)

    item = visions.get(slug)
    if not item:
        out.append(f"_⚠ vision `{slug}` w frontmatter, ale nie ma w indeksie. Uruchom `python ~/.claude/scripts/vision_catalog.py`._")
        return "\n".join(out)

    same_repo = repo_root / "design" / "visions" / f"{slug}.md"
    path = same_repo if same_repo.exists() else Path(item["path"])
    text = _read_text(path)
    title = item.get("title", slug)
    status = item.get("status", "?")
    progress = item.get("progress", {})

    out.append(f"**{title}** (`{slug}`) — status: {status}")
    out.append(f"- Plans: {progress.get('shipped', 0)} shipped / {progress.get('in_progress', 0)} in-progress / {progress.get('pending', 0)} pending")

    why = _extract_section(text, "## Why")
    if why:
        out.append("\n**Why:**")
        out.append(why.strip()[:500])

    dod = _extract_section(text, "## Definition of Done")
    if dod:
        out.append("\n**Definition of Done:**")
        out.append(dod.strip()[:500])

    next_plan = item.get("next_plan") or _roadmap_next(text)
    if next_plan:
        out.append(f"\n**Roadmap next:** {next_plan}")

    return "\n".join(out)


def _extract_section(text: str, header: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip().lower() == header.lower():
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            out.append(line)
    return "\n".join(out).strip()


def _roadmap_next(text: str) -> str:
    in_roadmap = False
    for line in text.splitlines():
        if line.strip().lower() == "## roadmap":
            in_roadmap = True
            continue
        if in_roadmap and line.startswith("## "):
            break
        if in_roadmap and "- [ ]" in line:
            return line.strip()
    return ""


def _section_idea_box(repo_root: Path) -> str:
    out = ["## IDEA_BOX (repo + global)"]
    repo_box = repo_root / "IDEA_BOX.md"
    if repo_box.exists():
        text = _read_text(repo_box)
        out.append(f"\n**{repo_root.name}/IDEA_BOX.md:**")
        out.append(_compact_idea_box(text, 30))
    else:
        out.append(f"_(brak IDEA_BOX.md w {repo_root.name})_")

    if ECOSYSTEM_BOX.exists():
        text = _read_text(ECOSYSTEM_BOX)
        out.append("\n**ECOSYSTEM_IDEA_BOX.md (cross-repo):**")
        out.append(_compact_idea_box(text, 20))

    return "\n".join(out)


def _compact_idea_box(text: str, max_lines: int) -> str:
    """Extract bullet-list entries, drop deep prose, cap to max_lines."""
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        s = line.rstrip()
        if not s:
            continue
        if s.startswith("# ") or s.startswith("## ") or s.startswith("### "):
            kept.append(s)
        elif s.lstrip().startswith(("- ", "* ", "1. ", "2. ")):
            kept.append(s)
        if len(kept) >= max_lines:
            kept.append(f"... _(truncated, {len(lines)} lines total)_")
            break
    return "\n".join(kept) if kept else "_(empty)_"


def _section_plans(repo_slugs: list[str]) -> str:
    out = ["## PLANS.md (related)"]
    if not PLANS_CATALOG.exists():
        out.append("_(PLANS.md missing — uruchom `python ~/.claude/scripts/plan_catalog.py`)_")
        return "\n".join(out)

    text = _read_text(PLANS_CATALOG)
    cross_repo = _extract_section(text, "## Cross-repo Plans (repos.length > 1)")
    in_progress = ""
    drafts = ""
    for rs in repo_slugs:
        ip = _extract_section_starting_with(text, "## In Progress", rs)
        dr = _extract_section_starting_with(text, "## Draft", rs)
        if ip and not in_progress:
            in_progress = ip
        if dr and not drafts:
            drafts = dr

    if cross_repo:
        relevant = "\n".join(
            line for line in cross_repo.splitlines()
            if any(rs in line.lower() for rs in repo_slugs) or "ecosystem" in line.lower()
        )
        if relevant.strip():
            out.append("\n**Cross-repo plans involving this repo:**")
            out.append(relevant[:1500])

    primary = repo_slugs[0]
    if in_progress:
        out.append(f"\n**In progress in `{primary}`:**")
        out.append(in_progress[:1200])

    if drafts:
        out.append(f"\n**Drafts in `{primary}`:**")
        out.append(drafts[:1200])

    if not (cross_repo or in_progress or drafts):
        out.append(f"_(no active/draft/cross-repo plans for {primary})_")

    return "\n".join(out)


def _extract_section_starting_with(text: str, header: str, repo_slug: str) -> str:
    """Extract `### <repo-slug>` subsection inside `## <header>`."""
    lines = text.splitlines()
    out: list[str] = []
    in_main = False
    in_repo = False
    for line in lines:
        if line.strip() == header:
            in_main = True
            continue
        if in_main and line.startswith("## ") and line.strip() != header:
            break
        if not in_main:
            continue
        if line.startswith("### "):
            in_repo = repo_slug.lower() in line.lower()
            continue
        if in_repo:
            out.append(line)
    return "\n".join(out).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan context loader (PRE)")
    parser.add_argument("--cwd", help="Working directory (defaults to $PWD)")
    parser.add_argument("--repo", help="Repo slug (overrides cwd detection)")
    parser.add_argument("--plan", help="Plan path (relative or absolute)")
    parser.add_argument("--quiet-empty", action="store_true",
                        help="Suppress block if all sections empty")
    args = parser.parse_args()

    cwd = Path(args.cwd or os.getcwd()).resolve()

    if args.repo:
        repo_root = BASE / args.repo
        if not repo_root.exists():
            for p in BASE.iterdir():
                if _slugify_repo(p.name) == args.repo.lower():
                    repo_root = p
                    break
    else:
        repo_root = _detect_repo(cwd)

    if not repo_root or not repo_root.exists():
        print(f"<plan-context>\n_(could not detect repo from cwd={cwd})_\n</plan-context>")
        return 0

    repo_slugs = _repo_slug_variants(repo_root)

    plan_path = None
    if args.plan:
        p = Path(args.plan)
        if not p.is_absolute():
            p = (repo_root / p).resolve()
        plan_path = p

    sections = [
        f"<plan-context repo=\"{repo_slugs[0]}\" cwd=\"{cwd.as_posix()}\">",
        "_Auto-loaded by plan_context_loader.py — read this BEFORE designing/coding._",
        "",
        _section_vision(plan_path, repo_slugs, repo_root),
        "",
        _section_idea_box(repo_root),
        "",
        _section_plans(repo_slugs),
        "",
        "## How to use",
        "1. Reference vision Why+DoD when scoping the plan.",
        "2. Cross-check IDEA_BOX — if this work resolves an item, mark it.",
        "3. Avoid duplicating work already in PLANS.md (in-progress or draft).",
        "4. After landing: AI MUST run `python ~/.claude/scripts/plan_context_updater.py --plan <path>`.",
        "</plan-context>",
    ]

    print("\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
