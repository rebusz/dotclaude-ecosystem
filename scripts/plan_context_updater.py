#!/usr/bin/env python3
"""Post-step updater for plan/module completion.

Regenerates global catalogs (PLANS.md, VISIONS.md), optionally appends a
completion log entry to the plan's vision auto-log, and marks resolved
IDEA_BOX entries.

Usage:
    python plan_context_updater.py --plan design/plans/2026-05-09_foo.md
    python plan_context_updater.py --plan ... --shipped --note "Phases 1-3 done"
    python plan_context_updater.py --plan ... --resolved-ideas "discord-rapid-ocr,bias-gauge-recal"

Best-effort: errors print to stderr but never raise.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home() / ".claude"
BASE = Path("d:/APPS")
SCRIPTS = HOME / "scripts"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def _resolve_plan(plan_arg: str) -> Path | None:
    p = Path(plan_arg)
    if p.is_absolute() and p.exists():
        return p
    cwd = Path(os.getcwd()).resolve()
    candidate = (cwd / p).resolve()
    if candidate.exists():
        return candidate
    return None


def _parse_plan_meta(plan: Path) -> dict:
    """Pull frontmatter `vision:`, `repos:`, `status:` from plan."""
    meta: dict = {}
    text = _read_text(plan)
    if not text.startswith("---"):
        return meta
    in_block = False
    for line in text.splitlines()[:60]:
        if line.strip() == "---":
            if in_block:
                break
            in_block = True
            continue
        if not in_block:
            continue
        for key in ("vision", "status", "title"):
            if line.startswith(f"{key}:"):
                value = line.split(":", 1)[1].strip().strip("\"'")
                meta[key] = value
    return meta


def _regen_catalog(name: str) -> tuple[bool, str]:
    script = SCRIPTS / f"{name}.py"
    if not script.exists():
        return False, f"{name}.py not found"
    try:
        r = subprocess.run(
            ["python", str(script)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "unknown error")[:300]
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:300]


def _append_vision_log(vision_path: Path, plan_slug: str, note: str) -> bool:
    """Insert log entry between AUTO-LOG markers in vision file."""
    BEGIN = "<!-- BEGIN AUTO-LOG"
    END = "<!-- END AUTO-LOG -->"
    text = _read_text(vision_path)
    if not text or BEGIN not in text or END not in text:
        return False
    today = datetime.utcnow().date().isoformat()
    entry = f"- {today} — {plan_slug}: {note}".rstrip(": ")
    pre, rest = text.split(BEGIN, 1)
    block, post = rest.split(END, 1)
    block_lines = block.splitlines()
    head = block_lines[0] if block_lines else ""
    body = [ln for ln in block_lines[1:] if ln.strip() and not ln.startswith("<!--")]
    body.append(entry)
    new_block = head + "\n" + "\n".join(body) + "\n"
    new_text = pre + BEGIN + new_block + END + post
    _atomic_write(vision_path, new_text)
    return True


def _resolve_vision_path(slug: str, plan_path: Path | None = None) -> Path | None:
    """Resolve vision file path for a slug.

    Preference order:
    1. Same-repo as plan: <plan_repo>/design/visions/<slug>.md (avoids worktree confusion)
    2. Indexed path from .vision_index.json
    """
    if plan_path:
        repo_root = plan_path
        while repo_root.parent != BASE and repo_root.parent != repo_root:
            repo_root = repo_root.parent
        if repo_root.parent == BASE:
            same_repo = repo_root / "design" / "visions" / f"{slug}.md"
            if same_repo.exists():
                return same_repo

    import json
    idx = HOME / ".vision_index.json"
    if not idx.exists():
        return None
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except Exception:
        return None
    item = data.get("visions", {}).get(slug)
    if not item:
        return None
    p = Path(item["path"])
    return p if p.exists() else None


def _strike_idea_entries(repo_root: Path, slugs: list[str]) -> int:
    """Mark resolved IDEA_BOX entries — append (DONE YYYY-MM-DD) to lines containing slug."""
    if not slugs:
        return 0
    box = repo_root / "IDEA_BOX.md"
    if not box.exists():
        return 0
    text = _read_text(box)
    today = datetime.utcnow().date().isoformat()
    changed = 0
    new_lines: list[str] = []
    for line in text.splitlines():
        marked = False
        for slug in slugs:
            if slug in line and "(DONE " not in line:
                line = line.rstrip() + f" (DONE {today})"
                changed += 1
                marked = True
                break
        new_lines.append(line)
    if changed:
        _atomic_write(box, "\n".join(new_lines) + "\n")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan context updater (POST)")
    parser.add_argument("--plan", required=True, help="Plan path (relative or absolute)")
    parser.add_argument("--shipped", action="store_true",
                        help="Mark completion event in vision auto-log")
    parser.add_argument("--note", default="", help="Log note (optional)")
    parser.add_argument("--resolved-ideas", default="",
                        help="Comma-separated IDEA_BOX entry slugs to mark DONE")
    parser.add_argument("--skip-catalogs", action="store_true",
                        help="Skip plan_catalog.py + vision_catalog.py regen")
    args = parser.parse_args()

    plan = _resolve_plan(args.plan)
    if not plan:
        print(f"ERROR: plan not found: {args.plan}", file=sys.stderr)
        return 1

    meta = _parse_plan_meta(plan)
    plan_slug = plan.stem
    if len(plan_slug) > 11 and plan_slug[:10].count("-") == 2 and plan_slug[10] in ("_", "-"):
        plan_slug = plan_slug[11:]

    repo_root = plan
    while repo_root.parent != BASE and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    if repo_root.parent != BASE:
        repo_root = None

    summary: list[str] = []

    if not args.skip_catalogs:
        ok, msg = _regen_catalog("plan_catalog")
        summary.append(f"PLANS.md regen: {'OK' if ok else 'FAIL — ' + msg}")
        ok, msg = _regen_catalog("vision_catalog")
        summary.append(f"VISIONS.md regen: {'OK' if ok else 'FAIL — ' + msg}")

    vision_slug = meta.get("vision")
    if vision_slug:
        vp = _resolve_vision_path(vision_slug, plan_path=plan)
        if vp and args.shipped:
            note = args.note or f"plan {meta.get('status', 'updated')}"
            if _append_vision_log(vp, plan_slug, note):
                summary.append(f"vision `{vision_slug}` auto-log: appended")
            else:
                summary.append(f"vision `{vision_slug}` auto-log: SKIP (no markers)")
        elif vp:
            summary.append(f"vision `{vision_slug}` linked (no --shipped, log skipped)")
        else:
            summary.append(f"vision `{vision_slug}` NOT FOUND in index")
    else:
        summary.append("plan has no `vision:` frontmatter (skipped vision update)")

    if args.resolved_ideas and repo_root:
        slugs = [s.strip() for s in args.resolved_ideas.split(",") if s.strip()]
        n = _strike_idea_entries(repo_root, slugs)
        summary.append(f"IDEA_BOX entries marked DONE: {n}/{len(slugs)}")

    print("plan_context_updater summary:")
    for line in summary:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
