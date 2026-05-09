#!/usr/bin/env python3
"""Global Vision Catalog - generates ~/.claude/VISIONS.md and .vision_index.json."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from _catalog_common import EXCLUSIONS, discover_repos, parse_yaml_block

HOME = Path.home() / ".claude"
OUTPUT = HOME / "VISIONS.md"
INDEX_OUTPUT = HOME / ".vision_index.json"
FAIL_QUEUE = HOME / ".vision_log_failed.jsonl"
BASE = "d:/APPS"
SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VISION_TAG_RE = re.compile(r"\[VISION:\s*([a-z0-9-]+)\s*\]")
AUTO_STATE_BEGIN = "<!-- BEGIN AUTO-STATE"
AUTO_STATE_END = "<!-- END AUTO-STATE -->"
EXTRA_EXCLUSIONS = frozenset(["_shared", "_status", "Prompts"])


def canonical_path(path: Path) -> str:
    return path.resolve().as_posix()


def _slugify(text: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-+", "-", raw) or "untitled"


def _repo_slug(path: Path) -> str:
    return path.name.lower().replace(" ", "-")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def discover_all_repos(base: str = BASE) -> list[Path]:
    roots: set[Path] = set()
    try:
        roots.update(discover_repos(base))
    except FileNotFoundError:
        return []
    base_path = Path(base)
    for child in base_path.iterdir():
        if not child.is_dir():
            continue
        if child.name in EXCLUSIONS or child.name in EXTRA_EXCLUSIONS or child.name.startswith("_"):
            continue
        roots.add(child)
    for match in base_path.glob("*/design/visions"):
        if match.is_dir():
            roots.add(match.parent.parent)
    return sorted(roots, key=lambda p: p.name.lower())


def _master_agent_files(repos: list[Path]) -> list[Path]:
    return sorted(
        [repo / "Prompts" / "master_agent.md" for repo in repos if (repo / "Prompts" / "master_agent.md").exists()],
        key=lambda p: p.as_posix().lower(),
    )


def _vision_files(repos: list[Path]) -> list[Path]:
    files: list[Path] = []
    for repo in repos:
        target = repo / "design" / "visions"
        if target.exists():
            files.extend(sorted(target.glob("*.md")))
    return files


def _plan_files(repos: list[Path]) -> list[Path]:
    files: list[Path] = []
    for repo in repos:
        target = repo / "design" / "plans"
        if target.exists():
            files.extend(sorted(target.glob("*.md")))
    return files


def _idea_boxes(repos: list[Path]) -> list[Path]:
    paths = [HOME / "ECOSYSTEM_IDEA_BOX.md"]
    for repo in repos:
        p = repo / "IDEA_BOX.md"
        if p.exists():
            paths.append(p)
    return paths


def _has_closed_frontmatter(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8-sig") as f:
            if f.readline().strip() != "---":
                return False
            for i, line in enumerate(f):
                if line.strip() == "---":
                    return True
                if i > 100:
                    return False
    except OSError:
        return False
    return False


def _date_from_plan(path: Path, raw: dict[str, Any]) -> str:
    value = str(raw.get("date", ""))
    if DATE_RE.fullmatch(value):
        return value
    match = DATE_RE.search(path.stem)
    if match:
        return match.group()
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except OSError:
        return date.today().isoformat()


def _plan_slug(path: Path) -> str:
    stem = path.stem
    if len(stem) > 11 and DATE_RE.fullmatch(stem[:10]) and stem[10] in ("_", "-"):
        return stem[11:]
    return stem


def _section_lines(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return lines[start:end]


def _roadmap_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in _section_lines(text, "Roadmap"):
        stripped = line.strip()
        match = re.search(r"- \[([ xX])\]\s*(.+)$", stripped)
        if not match:
            continue
        done = match.group(1).lower() == "x"
        label = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: m.group(0).split("](")[0].lstrip("["), match.group(2))
        label = re.sub(r"[*_`]", "", label).strip()
        items.append({"done": done, "label": label, "slug": _slugify(label)})
    return items


def _next_from_roadmap(text: str) -> str:
    for item in _roadmap_items(text):
        if not item["done"]:
            return item["slug"]
    return "none"


def _file_uri(path: str) -> str:
    encoded = path.replace(" ", "%20")
    return f"file:///{encoded}" if len(encoded) > 1 and encoded[1] == ":" else f"file:///{encoded}"


def _parse_plans(repos: list[Path]) -> dict[str, list[dict[str, Any]]]:
    by_vision: dict[str, list[dict[str, Any]]] = {}
    for path in _plan_files(repos):
        raw = parse_yaml_block(path)
        slug = str(raw.get("vision", "")).strip()
        if not slug:
            continue
        status = str(raw.get("status", "unknown")).strip().lower() or "unknown"
        entry = {
            "path": canonical_path(path),
            "status": status,
            "slug": _plan_slug(path),
            "title": str(raw.get("title") or _plan_slug(path)),
            "date": _date_from_plan(path, raw),
        }
        by_vision.setdefault(slug, []).append(entry)
    for entries in by_vision.values():
        entries.sort(key=lambda e: (e["date"], e["path"]))
    return by_vision


def _count_ideas(repos: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _idea_boxes(repos):
        try:
            text = _read_text(path)
        except OSError:
            continue
        for slug in VISION_TAG_RE.findall(text):
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def _progress(plans: list[dict[str, Any]], roadmap_total: int) -> dict[str, int]:
    shipped = sum(1 for p in plans if p["status"] == "shipped")
    in_progress = sum(1 for p in plans if p["status"] == "in-progress")
    total = max(len(plans), roadmap_total)
    pending = max(total - shipped - in_progress, 0)
    return {"shipped": shipped, "in_progress": in_progress, "pending": pending, "total": total}


def _last_activity(plans: list[dict[str, Any]], created: str) -> str:
    dates = [p["date"] for p in plans if DATE_RE.fullmatch(str(p.get("date", "")))]
    return max(dates) if dates else created


def _auto_state(info: dict[str, Any]) -> str:
    progress = info["progress"]
    return "\n".join([
        "<!-- BEGIN AUTO-STATE - managed by /vision sync; manual edits will be overwritten -->",
        "## Current State",
        f"- Plans shipped: {progress['shipped']} / {progress['total']}",
        f"- Plans in progress: {progress['in_progress']}",
        f"- Plans pending: {progress['pending']}",
        f"- Open ideas waiting: {info['ideas_count']}",
        f"- Last activity: {info['last_activity']}",
        f"- Recommended next plan: **{info['next_plan']}**",
        "<!-- END AUTO-STATE -->",
    ])


def _replace_auto_state(text: str, block: str) -> str:
    if AUTO_STATE_BEGIN in text and AUTO_STATE_END in text:
        start = text.index(AUTO_STATE_BEGIN)
        end = text.index(AUTO_STATE_END, start) + len(AUTO_STATE_END)
        return text[:start].rstrip() + "\n\n" + block + "\n\n" + text[end:].lstrip()
    marker = "\n## Notes & Decisions"
    if marker in text:
        return text.replace(marker, "\n\n" + block + "\n" + marker, 1)
    return text.rstrip() + "\n\n" + block + "\n"


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    try:
        os.replace(tmp, path)
    except PermissionError as exc:
        print(f"vision_catalog: permission denied replacing {path}: {exc}", file=sys.stderr)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _apply_log_entry(slug: str, entry_tsv: str, visions: dict[str, dict[str, Any]]) -> bool:
    item = visions.get(slug)
    if not item:
        return False
    try:
        from vision_context import log_completion

        return log_completion(slug, entry_tsv, Path(item["path"]))
    except Exception:
        return False


def drain_fail_queue(visions: dict[str, dict[str, Any]]) -> None:
    if not FAIL_QUEUE.exists():
        return
    remaining: list[str] = []
    try:
        for line in FAIL_QUEUE.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not _apply_log_entry(str(item.get("slug", "")), str(item.get("entry_tsv", "")), visions):
                    remaining.append(line)
            except json.JSONDecodeError:
                remaining.append(line)
        if remaining:
            _write_text_atomic(FAIL_QUEUE, "\n".join(remaining) + "\n")
        else:
            FAIL_QUEUE.unlink(missing_ok=True)
    except OSError as exc:
        print(f"vision_catalog: failed to drain fail queue: {exc}", file=sys.stderr)


def build_index(update_state: bool = True) -> tuple[dict[str, Any], list[str], list[str]]:
    repos = discover_all_repos(BASE)
    plans_by_vision = _parse_plans(repos)
    ideas_by_vision = _count_ideas(repos)
    warnings: list[str] = []
    collisions: list[str] = []
    visions: dict[str, dict[str, Any]] = {}
    seen_paths: dict[str, list[str]] = {}

    for path in _vision_files(repos):
        if not _has_closed_frontmatter(path):
            warnings.append(f"- Malformed YAML/frontmatter skipped: `{canonical_path(path)}`")
            continue
        raw = parse_yaml_block(path)
        if not raw:
            warnings.append(f"- Empty or malformed YAML skipped: `{canonical_path(path)}`")
            continue
        file_slug = path.stem
        fm_slug = str(raw.get("slug", "")).strip()
        slug = file_slug
        if fm_slug and fm_slug != file_slug:
            warnings.append(f"- Slug mismatch in `{canonical_path(path)}`: frontmatter `{fm_slug}`, canonical `{file_slug}`")
        if not SLUG_RE.fullmatch(slug):
            warnings.append(f"- Invalid slug skipped: `{slug}` in `{canonical_path(path)}`")
            continue
        repos_raw = raw.get("repos", [_repo_slug(path.parents[2])])
        repos_list = repos_raw if isinstance(repos_raw, list) else [str(repos_raw)]
        repos_list = [_slugify(str(r)) for r in repos_list if str(r).strip()]
        if not repos_list:
            repos_list = [_repo_slug(path.parents[2])]
        primary_repo = str(raw.get("primary_repo", "")).strip() or repos_list[0]
        if len(repos_list) > 1 and not str(raw.get("primary_repo", "")).strip():
            warnings.append(f"- Cross-repo vision `{slug}` missing primary_repo; defaulted to `{primary_repo}`")
        if len(repos_list) > 1 and "-" not in slug:
            warnings.append(f"- Cross-repo vision `{slug}` is unprefixed")

        text = _read_text(path)
        plans = plans_by_vision.get(slug, [])
        roadmap_total = len(_roadmap_items(text))
        info = {
            "path": canonical_path(path),
            "title": str(raw.get("title") or slug),
            "slug": slug,
            "status": str(raw.get("status") or "draft"),
            "created": str(raw.get("created") or ""),
            "target": str(raw.get("target") or ""),
            "owner": str(raw.get("owner") or ""),
            "repos": repos_list,
            "primary_repo": _slugify(primary_repo),
            "progress": _progress(plans, roadmap_total),
            "plans": plans,
            "next_plan": _next_from_roadmap(text),
            "ideas_count": ideas_by_vision.get(slug, 0),
            "last_activity": _last_activity(plans, str(raw.get("created") or "")),
        }
        visions[slug] = info
        seen_paths.setdefault(slug, []).append(canonical_path(path))

    for slug, paths in sorted(seen_paths.items()):
        if len(paths) > 1:
            collisions.append(f"- `{slug}` appears in: {', '.join(paths)}")

    master_agents = _master_agent_files(repos)
    if master_agents:
        missing = []
        for master_agent in master_agents:
            text = _read_text(master_agent)
            if "## Vision-aware execution" not in text or "vision_context.py --plan" not in text:
                missing.append(canonical_path(master_agent))
        if missing:
            warnings.append("- master_agent.md vision preamble missing or incomplete in: " + ", ".join(f"`{p}`" for p in missing))
    else:
        warnings.append("- No repo `Prompts/master_agent.md` files found for vision-aware preamble check")

    if update_state:
        for info in visions.values():
            p = Path(info["path"])
            try:
                updated = _replace_auto_state(_read_text(p), _auto_state(info))
                _write_text_atomic(p, updated)
            except OSError as exc:
                warnings.append(f"- AUTO-STATE update failed for `{info['slug']}`: {exc}")

    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "visions": visions,
    }
    drain_fail_queue(visions)
    return index, warnings, collisions


def render_catalog(index: dict[str, Any], warnings: list[str], collisions: list[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    visions = index.get("visions", {})
    lines: list[str] = [f"# Vision Catalog (auto-generated {now})", ""]
    cross = [v for v in visions.values() if len(v.get("repos", [])) > 1]
    active = [v for v in visions.values() if len(v.get("repos", [])) <= 1 and v.get("status") not in ("shipped", "abandoned")]
    recently = [
        v for v in visions.values()
        if v.get("status") == "shipped" and str(v.get("last_activity", "")) >= (date.today() - timedelta(days=30)).isoformat()
    ]

    lines.append("## Cross-repo Visions (repos.length > 1)")
    if cross:
        for v in sorted(cross, key=lambda x: x["title"].lower()):
            p = v["progress"]
            lines.append(f"- [{v['title']}]({_file_uri(v['path'])}) - `{v['status']}` - {p['total']} plans ({p['shipped']} shipped, {p['in_progress']} in-progress, {p['pending']} pending) - repos: {v['repos']}")
    else:
        lines.append("(empty)")
    lines.append("")

    lines.append("## Active per Repo")
    if active:
        by_repo: dict[str, list[dict[str, Any]]] = {}
        for v in active:
            by_repo.setdefault(v.get("primary_repo") or v["repos"][0], []).append(v)
        for repo in sorted(by_repo):
            lines.append(f"### {repo}")
            for v in sorted(by_repo[repo], key=lambda x: x["title"].lower()):
                p = v["progress"]
                target = f" - target {v['target']}" if v.get("target") else ""
                lines.append(f"- [{v['title']}]({_file_uri(v['path'])}) - `{v['status']}`{target}")
                lines.append(f"  Plans: {p['shipped']}/{p['total']} shipped - Open ideas: {v['ideas_count']}")
                lines.append(f"  Next: {v['next_plan']}")
            lines.append("")
    else:
        lines.append("(empty)")
        lines.append("")

    lines.append("## Recently Shipped (last 30d)")
    if recently:
        for v in sorted(recently, key=lambda x: x["last_activity"], reverse=True):
            lines.append(f"- [{v['title']}]({_file_uri(v['path'])}) - shipped {v['last_activity']} - {v['progress']['total']} plans")
    else:
        lines.append("(empty)")
    lines.append("")

    lines.append("## Catalog warnings")
    lines.extend(warnings or ["(empty)"])
    lines.append("")
    lines.append("## Collisions")
    lines.extend(collisions or ["(empty)"])
    lines.append("")
    lines.append("## Stale (in-progress >90d) - V6 lint")
    lines.append("(empty)")
    return "\n".join(lines) + "\n"


def write_outputs(index: dict[str, Any], catalog: str) -> None:
    _write_text_atomic(OUTPUT, catalog)
    _write_text_atomic(INDEX_OUTPUT, json.dumps(index, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the global vision catalog.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    index, warnings, collisions = build_index(update_state=True)
    catalog = render_catalog(index, warnings, collisions)
    write_outputs(index, catalog)
    if args.verbose:
        print(
            f"[vision_catalog] {len(index['visions'])} visions | {len(warnings)} warnings | "
            f"{len(collisions)} collisions | wrote {OUTPUT} and {INDEX_OUTPUT}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
