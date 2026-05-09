#!/usr/bin/env python3
"""Small operator CLI for the /vision workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from vision_catalog import INDEX_OUTPUT, SLUG_RE, build_index, render_catalog, write_outputs

HOME = Path.home() / ".claude"
BASE = Path("d:/APPS")
INDEX = HOME / ".vision_index.json"
CATALOG = HOME / "VISIONS.md"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _load_index() -> dict:
    if not INDEX.exists():
        cmd_sync(argparse.Namespace(verbose=False))
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        cmd_sync(argparse.Namespace(verbose=False))
        return json.loads(INDEX.read_text(encoding="utf-8"))


def _repo_path(repo: str) -> Path:
    candidates = {p.name.lower().replace(" ", "-"): p for p in BASE.iterdir() if p.is_dir()}
    key = repo.lower().replace(" ", "-")
    if key not in candidates:
        raise SystemExit(f"ERROR: repo not found under d:/APPS: {repo}")
    return candidates[key]


def _slugify(text: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-+", "-", raw) or "untitled"


def _plan_slug(path: Path) -> str:
    stem = path.stem
    if len(stem) > 11 and DATE_RE.fullmatch(stem[:10]) and stem[10] in ("_", "-"):
        return stem[11:]
    return stem


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
    return "no plans pending"


def cmd_list(args: argparse.Namespace) -> None:
    if not CATALOG.exists():
        cmd_sync(args)
    print(CATALOG.read_text(encoding="utf-8", errors="replace"))


def cmd_show(args: argparse.Namespace) -> None:
    data = _load_index()
    item = data.get("visions", {}).get(args.slug)
    if not item:
        raise SystemExit(f"ERROR: vision not found: {args.slug}")
    path = Path(item["path"])
    print(path.read_text(encoding="utf-8", errors="replace"))


def _prompt_if_missing(value: str | None, prompt: str) -> str:
    if value:
        return value
    return input(prompt).strip()


def cmd_new(args: argparse.Namespace) -> None:
    data = _load_index()
    title = _prompt_if_missing(args.title, "Title: ")
    slug = args.slug or _slugify(title)
    slug = _prompt_if_missing(slug, "Slug: ")
    if not SLUG_RE.fullmatch(slug):
        raise SystemExit("ERROR: slug must match [a-z0-9-]+")
    if slug in data.get("visions", {}):
        raise SystemExit(f"ERROR: slug already exists: {slug}. Try a repo-prefixed alternative.")
    repo = _prompt_if_missing(args.repo, "Repo under d:/APPS: ")
    why = _prompt_if_missing(args.why, "Why (one paragraph): ")
    dod_raw = args.dod or input("Definition of Done bullets (separate with ';'): ").strip()
    milestones_raw = args.roadmap or input("Roadmap milestones (separate with ';'): ").strip()
    repos = [r.strip() for r in (args.repos or repo).split(",") if r.strip()]
    primary = args.primary_repo or repo
    if len(repos) > 1 and not primary:
        raise SystemExit("ERROR: primary_repo is required for cross-repo visions")

    root = _repo_path(primary)
    path = root / "design" / "visions" / f"{slug}.md"
    if path.exists():
        raise SystemExit(f"ERROR: file already exists: {path}")

    dod = [x.strip() for x in dod_raw.split(";") if x.strip()]
    milestones = [x.strip() for x in milestones_raw.split(";") if x.strip()]
    lines = [
        "---",
        f'title: "{title}"',
        f"slug: {slug}",
        "status: draft",
        f"created: {date.today().isoformat()}",
        "target: ",
        "owner: dszub",
        f"repos: [{', '.join(_slugify(r) for r in repos)}]",
        f"primary_repo: {_slugify(primary)}",
        "tags: []",
        "contracts: []",
        "---",
        "",
        f"# {title}",
        "",
        "## Why",
        why,
        "",
        "## Definition of Done",
    ]
    lines.extend([f"- {x}" for x in dod] or ["- TBD"])
    lines.extend(["", "## Roadmap"])
    lines.extend([f"{i}. - [ ] {x}" for i, x in enumerate(milestones, 1)] or ["1. - [ ] First plan TBD"])
    lines.extend([
        "",
        "<!-- BEGIN AUTO-STATE - managed by /vision sync; manual edits will be overwritten -->",
        "## Current State",
        "- Plans shipped: 0 / 0",
        "- Plans in progress: 0",
        "- Plans pending: 0",
        "- Open ideas waiting: 0",
        f"- Last activity: {date.today().isoformat()}",
        "- Recommended next plan: **none**",
        "<!-- END AUTO-STATE -->",
        "",
        "## Notes & Decisions",
        "",
        "<!-- BEGIN AUTO-LOG - managed by vision_context.py --log -->",
        "<!-- END AUTO-LOG -->",
        "",
    ])
    _atomic_write(path, "\n".join(lines))
    cmd_sync(argparse.Namespace(verbose=False))
    print(f"Created {path}")


def _upsert_frontmatter_field(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    field = f"{key}: {value}"
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, min(len(lines), 120)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            raise SystemExit(f"ERROR: malformed frontmatter: {path}")
        for i in range(1, end):
            if lines[i].startswith(f"{key}:"):
                lines[i] = field
                break
        else:
            lines.insert(end, field)
        updated = "\n".join(lines) + "\n"
    else:
        updated = f"---\n{field}\n---\n\n{text}"
    _atomic_write(path, updated)


def cmd_attach(args: argparse.Namespace) -> None:
    data = _load_index()
    if args.slug not in data.get("visions", {}):
        raise SystemExit(f"ERROR: unresolved vision slug: {args.slug}")
    path = Path(args.plan_path)
    if not path.exists():
        raise SystemExit(f"ERROR: plan not found: {path}")
    _upsert_frontmatter_field(path, "vision", args.slug)
    cmd_sync(argparse.Namespace(verbose=False))
    print(f"Attached {_plan_slug(path)} -> {args.slug}")


def cmd_next(args: argparse.Namespace) -> None:
    data = _load_index()
    item = data.get("visions", {}).get(args.slug)
    if not item:
        raise SystemExit(f"ERROR: vision not found: {args.slug}")
    text = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
    print(_roadmap_next(text))


def cmd_sync(args: argparse.Namespace) -> None:
    index, warnings, collisions = build_index(update_state=True)
    write_outputs(index, render_catalog(index, warnings, collisions))
    if getattr(args, "verbose", False):
        print(f"Synced {len(index.get('visions', {}))} visions to {INDEX_OUTPUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description="/vision workflow CLI")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("slug")
    new = sub.add_parser("new")
    new.add_argument("--title")
    new.add_argument("--slug")
    new.add_argument("--repo")
    new.add_argument("--repos")
    new.add_argument("--primary-repo")
    new.add_argument("--why")
    new.add_argument("--dod")
    new.add_argument("--roadmap")
    attach = sub.add_parser("attach")
    attach.add_argument("plan_path")
    attach.add_argument("slug")
    nxt = sub.add_parser("next")
    nxt.add_argument("slug")
    sync = sub.add_parser("sync")
    sync.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    if not args.cmd or args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "new":
        cmd_new(args)
    elif args.cmd == "attach":
        cmd_attach(args)
    elif args.cmd == "next":
        cmd_next(args)
    elif args.cmd == "sync":
        cmd_sync(args)


if __name__ == "__main__":
    main()
