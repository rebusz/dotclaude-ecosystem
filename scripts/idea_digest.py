#!/usr/bin/env python3
"""Ecosystem Idea Digest — ranked cross-repo P1→P3 list with [CROSS-REPO] flagging.

Usage:
    python idea_digest.py               # full digest
    python idea_digest.py --prio 1      # P1 only
    python idea_digest.py --repo WatchF # one repo only
    python idea_digest.py add           # interactive: add idea to a box
    python idea_digest.py add "text" --repo Tsignal --prio 2 --effort M --section bug
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from _catalog_common import discover_repos, EXCLUSIONS, walk_repos, parse_yaml_block  # noqa: F401

# Force UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

REPO_ALIASES = {
    "Obsidian Flow": "OF",
    "Tsignal 5.0": "Tsignal",
}


def discover_idea_boxes(base: str = "d:/APPS") -> dict[str, str]:
    """Discover IDEA_BOX.md across all local repos, plus the global ecosystem box."""
    boxes: dict[str, str] = {}
    base_path = Path(base)
    if base_path.exists():
        for child in sorted(base_path.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("_") or child.name in {"Older", "Saved", "Prompts"}:
                continue
            box = child / "IDEA_BOX.md"
            if box.exists():
                label = REPO_ALIASES.get(child.name, child.name)
                boxes[label] = box.as_posix()
    boxes["Global"] = (Path.home() / ".claude" / "ECOSYSTEM_IDEA_BOX.md").as_posix()
    return boxes


REPOS = discover_idea_boxes()

SECTIONS = {
    "feature":  "## Feature Ideas",
    "bug":      "## Bug Fixes / TODOs",
    "module":   "## New Modules",
    "test":     "## Test Coverage Gaps",
    "refactor": "## Refactoring Ideas",
}

P1_CAP = 5
ITEM_RE = re.compile(r"^\s*-\s+(\[P[123]\](?:\[(?:S|M|L|XL)\])?)\s+(.+)$")
PRIO_RE = re.compile(r"\[P([123])\]")
CROSS_RE = re.compile(r"\[CROSS-REPO[^\]]*\]", re.IGNORECASE)
VISION_TAG_RE = re.compile(r"\[VISION:\s*([a-z0-9-]+)\s*\]")


# ── READ ──────────────────────────────────────────────────────────────────────

def parse_box(repo_name: str, path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"  WARNING: {repo_name} box not found: {path}")
        return []
    items = []
    in_archived = False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("## Archived"):
            in_archived = True
        if in_archived:
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        tags_str, text = m.group(1), m.group(2)
        prio_m = PRIO_RE.search(tags_str)
        if not prio_m:
            continue
        prio = int(prio_m.group(1))
        items.append({
            "repo": repo_name,
            "prio": prio,
            "text": text.strip(),
            "cross": bool(CROSS_RE.search(text)),
            "vision": VISION_TAG_RE.search(text).group(1) if VISION_TAG_RE.search(text) else "",
        })
    return items


def cmd_digest(args: argparse.Namespace) -> None:
    today = date.today().isoformat()
    print(f"=== Ecosystem Idea Digest ({today}) ===\n")

    all_items: list[dict] = []
    p1_counts: dict[str, int] = {}

    target_repos = {args.repo: REPOS[args.repo]} if args.repo else REPOS
    for repo_name, path in target_repos.items():
        items = parse_box(repo_name, path)
        all_items.extend(items)
        p1_counts[repo_name] = sum(1 for i in items if i["prio"] == 1)

    prio_range = [args.prio] if args.prio else [1, 2, 3]
    any_output = False

    for prio in prio_range:
        group = [i for i in all_items if i["prio"] == prio]
        if not group:
            continue
        any_output = True
        regular = [i for i in group if not i["cross"]]
        cross   = [i for i in group if i["cross"]]
        print(f"--- P{prio} ({len(group)} items) ---")
        for item in regular:
            print(f"  [P{prio}] {item['repo']}: {item['text']}")
        for item in cross:
            print(f"  [P{prio}] {item['repo']}: {item['text']}  ← CROSS-REPO")
        print()

    if not any_output:
        print("(no items found)")
        return

    p1 = sum(1 for i in all_items if i["prio"] == 1)
    p2 = sum(1 for i in all_items if i["prio"] == 2)
    p3 = sum(1 for i in all_items if i["prio"] == 3)
    cross_total = sum(1 for i in all_items if i["cross"])
    print(f"{p1} P1 items | {p2} P2 items | {p3} P3 items  ({len(all_items)} total)")
    print(f"{cross_total} items tagged [CROSS-REPO] — need coordination")

    caps = [f"{r}: {c} P1 items (cap is {P1_CAP})" for r, c in p1_counts.items() if c > P1_CAP]
    print(f"P1 cap warnings: {' | '.join(caps) if caps else '<none>'}")


def _load_vision_titles() -> dict[str, str]:
    index_path = Path.home() / ".claude" / ".vision_index.json"
    if not index_path.exists():
        return {}
    try:
        import json

        data = json.loads(index_path.read_text(encoding="utf-8"))
        return {
            slug: str(item.get("title") or slug)
            for slug, item in data.get("visions", {}).items()
        }
    except Exception:
        return {}


def cmd_by_vision(args: argparse.Namespace) -> None:
    today = date.today().isoformat()
    print(f"=== Ecosystem Idea Digest by Vision ({today}) ===\n")

    target_repos = {args.repo: REPOS[args.repo]} if args.repo else REPOS
    all_items: list[dict] = []
    for repo_name, path in target_repos.items():
        all_items.extend(parse_box(repo_name, path))

    prio_filter = args.prio
    if prio_filter:
        all_items = [i for i in all_items if i["prio"] == prio_filter]

    titles = _load_vision_titles()
    grouped: dict[str, list[dict]] = {}
    uncategorized: list[dict] = []
    no_vision: list[dict] = []

    for item in all_items:
        slug = item.get("vision", "")
        if not slug:
            no_vision.append(item)
        elif slug in titles:
            grouped.setdefault(slug, []).append(item)
        else:
            uncategorized.append(item)

    any_output = False
    for slug in sorted(grouped, key=lambda s: titles.get(s, s).lower()):
        any_output = True
        print(f"--- {titles.get(slug, slug)} [{slug}] ({len(grouped[slug])} items) ---")
        for item in sorted(grouped[slug], key=lambda i: (i["prio"], i["repo"])):
            print(f"  [P{item['prio']}] {item['repo']}: {item['text']}")
        print()

    if uncategorized:
        any_output = True
        print(f"--- Uncategorized (unknown vision tag) ({len(uncategorized)} items) ---")
        for item in sorted(uncategorized, key=lambda i: (i.get("vision", ""), i["prio"], i["repo"])):
            print(f"  [P{item['prio']}] {item['repo']}: {item['text']}")
        print()

    if no_vision:
        any_output = True
        print(f"--- No vision tag ({len(no_vision)} items) ---")
        for item in sorted(no_vision, key=lambda i: (i["prio"], i["repo"])):
            print(f"  [P{item['prio']}] {item['repo']}: {item['text']}")
        print()

    if not any_output:
        print("(no items found)")


# ── WRITE ─────────────────────────────────────────────────────────────────────

def _pick(prompt: str, options: list[tuple[str, str]]) -> str:
    """Numbered menu. options = [(value, label), ...]. Returns value."""
    for i, (val, label) in enumerate(options, 1):
        print(f"  {i}. {val} — {label}")
    values = [v for v, _ in options]
    while True:
        raw = input(f"{prompt} [1-{len(options)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return values[int(raw) - 1]
        if raw.upper() in [v.upper() for v in values]:
            return raw.upper()
        print(f"  Enter a number 1-{len(options)}.")


def _append_item(path: Path, section_header: str, new_line: str) -> None:
    """Insert new_line at the end of the matching section (before blank line + next ##)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_section = False
    insert_at = None

    for i, line in enumerate(lines):
        if line.strip() == section_header:
            in_section = True
            continue
        if in_section:
            # Next section or archived separator → insert just before this line
            if line.startswith("## ") or line.strip() == "---":
                # back up past trailing blank lines
                insert_at = i
                while insert_at > 0 and lines[insert_at - 1].strip() == "":
                    insert_at -= 1
                break

    if insert_at is None:
        # Section found but nothing after it (end of file before ---)
        insert_at = len(lines)

    lines.insert(insert_at, new_line)

    # Update last_updated field
    for i, line in enumerate(lines):
        if line.startswith("last_updated:"):
            lines[i] = f"last_updated: {date.today().isoformat()}"
            break

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_add(args: argparse.Namespace) -> None:
    print("\n=== Add Idea ===\n")

    # ── repo ──
    if args.repo:
        repo = args.repo
    else:
        print("Repo:")
        repo = _pick("Choose", [(r, REPOS[r].split("/")[-2] if "/" in REPOS[r] else r) for r in REPOS])

    box_path = Path(REPOS[repo])
    if not box_path.exists():
        print(f"ERROR: box not found at {box_path}")
        sys.exit(1)

    # ── section ──
    section_labels = {
        "feature":  "new feature / enhancement",
        "bug":      "bug fix / TODO",
        "module":   "new module",
        "test":     "test coverage gap",
        "refactor": "refactoring idea",
    }
    if args.section:
        section_key = args.section
    else:
        print("\nSection:")
        section_key = _pick("Choose", list(section_labels.items()))
    section_header = SECTIONS[section_key]

    # ── priority ──
    if args.prio:
        prio = args.prio
    else:
        print("\nPriority:")
        prio = int(_pick("Choose", [
            ("1", "P1 — must fix / do soon"),
            ("2", "P2 — important, not urgent"),
            ("3", "P3 — nice to have"),
        ]))

    # ── effort ──
    if args.effort:
        effort = args.effort.upper()
    else:
        print("\nEffort:")
        effort = _pick("Choose", [
            ("S", "small  (<1h)"),
            ("M", "medium (1–4h)"),
            ("L", "large  (>4h)"),
        ])

    # ── text ──
    if args.text:
        text = args.text
    else:
        print()
        text = input("Idea text: ").strip()
        if not text:
            print("Aborted — empty text.")
            sys.exit(0)

    # ── cross-repo ──
    cross_tag = ""
    interactive = sys.stdin.isatty()
    if args.cross is not None:
        cross_tag = f" [CROSS-REPO: {args.cross}]" if args.cross else ""
    elif interactive and not getattr(args, "yes", False):
        print("\nCross-repo? (Enter to skip, or type target repo names e.g. 'WatchF, OF')")
        cross_raw = input("Cross-repo targets: ").strip()
        if cross_raw:
            cross_tag = f" [CROSS-REPO: {cross_raw}]"

    # ── build item line ──
    new_line = f"- [P{prio}][{effort}] {text}{cross_tag}"

    # ── preview + confirm ──
    print(f"\nWill add to {repo} / {section_header}:")
    print(f"  {new_line}")
    if interactive and not getattr(args, "yes", False):
        confirm = input("\nConfirm? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("Aborted.")
            sys.exit(0)

    # P1 cap warning
    if prio == 1:
        current_p1 = sum(1 for i in parse_box(repo, REPOS[repo]) if i["prio"] == 1)
        if current_p1 >= P1_CAP:
            print(f"\nWARNING: {repo} already has {current_p1} P1 items (cap is {P1_CAP}).")
            print("Consider downgrading an existing P1 before adding another.")
            if interactive and not getattr(args, "yes", False):
                go = input("Add anyway? [y/N]: ").strip().lower()
                if go not in ("y", "yes"):
                    print("Aborted.")
                    sys.exit(0)

    _append_item(box_path, section_header, new_line)
    print(f"\nAdded to {box_path.name} ({repo}).")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ecosystem Idea Digest & Capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    # digest (default when no subcommand)
    d = sub.add_parser("digest", help="Show ranked digest (default)")
    d.add_argument("--prio", type=int, choices=[1, 2, 3])
    d.add_argument("--repo", choices=list(REPOS.keys()))
    d.add_argument("--by-vision", action="store_true", help="Group digest by [VISION: slug] tags")

    # add
    a = sub.add_parser("add", help="Add an idea to a box")
    a.add_argument("text", nargs="?", help="Idea text (omit for interactive)")
    a.add_argument("--repo",    choices=list(REPOS.keys()))
    a.add_argument("--prio",   type=int, choices=[1, 2, 3])
    a.add_argument("--effort", choices=["S", "M", "L", "s", "m", "l"])
    a.add_argument("--section", choices=list(SECTIONS.keys()))
    a.add_argument("--cross",  metavar="REPOS", help="e.g. 'WatchF, OF'")
    a.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")

    # top-level --prio / --repo for bare invocation (no subcommand)
    parser.add_argument("--prio", type=int, choices=[1, 2, 3])
    parser.add_argument("--repo", choices=list(REPOS.keys()))
    parser.add_argument("--by-vision", action="store_true", help="Group digest by [VISION: slug] tags")

    args = parser.parse_args()

    if args.cmd == "add":
        cmd_add(args)
    elif getattr(args, "by_vision", False):
        cmd_by_vision(args)
    else:
        # digest is the default
        cmd_digest(args)


if __name__ == "__main__":
    main()
