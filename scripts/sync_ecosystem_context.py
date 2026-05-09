#!/usr/bin/env python3
"""Sync local ecosystem context to private GitHub repo.

Reads:
  - ~/.claude/MEMORY.md + ~/.claude/projects/*/memory/*.md
  - ~/.claude/PLANS.md, VISIONS.md, ECOSYSTEM_IDEA_BOX.md
  - <repo>/IDEA_BOX.md for each repo under d:/APPS
  - <repo>/design/visions/*.md
  - <repo>/design/plans/*.md (last 30 days)

Sanitizes (regex strip secrets, P&L, broker IDs, absolute paths) before writing.

Writes to TARGET (default: D:/dotclaude/ecosystem-context):
  - INSTRUCTIONS.md            (copied from template)
  - MEMORY.md                  (compiled + sanitized)
  - VISIONS.md                 (auto-gen)
  - PLANS.md                   (auto-gen)
  - ECOSYSTEM_IDEA_BOX.md      (sanitized)
  - visions/<slug>.md          (sanitized)
  - plans/<date>_<slug>.md     (sanitized, last 30 days)
  - idea_boxes/<repo>.md       (sanitized)
  - _meta/last_synced.json

Optionally commits + pushes (--push). Otherwise just stages.

Usage:
  python sync_ecosystem_context.py --target "D:/dotclaude/ecosystem-context"
  python sync_ecosystem_context.py --target ... --push --note "manual sync"
  python sync_ecosystem_context.py --target ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home() / ".claude"
BASE = Path("d:/APPS")
EXCLUDED_REPOS = {"_dotclaude", "_shared", "_status", "Saved", "Older", "Prompts"}

# Sanitization patterns
DENY_FILES = [
    re.compile(r"auth\.json$", re.IGNORECASE),
    re.compile(r".*\.token$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r"\.env(\..*)?$", re.IGNORECASE),
    re.compile(r"credentials.*", re.IGNORECASE),
]

# Inline replacement patterns (run on every text body before writing)
SANITIZE_RULES: list[tuple[re.Pattern, str]] = [
    # Absolute paths d:/APPS/<repo>/... → <repo>/...
    (re.compile(r"[Dd]:[\\/]+APPS[\\/]+([A-Za-z0-9 _-]+?)[\\/]+", re.IGNORECASE),
     r"<\1>/"),
    # Bare absolute Windows paths d:/... → /<redacted-path>/
    (re.compile(r"[A-Za-z]:[\\/](?:Users|Program Files|ProgramData)[\\/][^\s\"'<>)]+", re.IGNORECASE),
     "<redacted-local-path>"),
    # P&L explicit dollar amounts ($-470, $1,234, etc.)
    (re.compile(r"\$[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?\b"), "$<redacted-pnl>"),
    # P&L (P&L: -$470, daily P&L $-470, P&L $123.45)
    (re.compile(r"(P&L\s*[:=]?\s*)[-+]?\$?\d+(?:[,.]\d+)?", re.IGNORECASE),
     r"\1<redacted-pnl>"),
    # WR (win rate) percentages tied to specific numbers
    (re.compile(r"(WR\s+)\d{1,3}%", re.IGNORECASE), r"\1<redacted-wr>"),
    # Broker account IDs (rough heuristic: long alphanum after broker name)
    (re.compile(r"(Questrade|IBKR|ProjectX|Tradovate)\s+(account|acct)[:\s#]+\w+",
                re.IGNORECASE), r"\1 \2 <redacted>"),
    # API keys / tokens (AWS, GitHub, generic high-entropy)
    (re.compile(r"\b(AKIA|gho_|ghp_|github_pat_|sk-)[A-Za-z0-9_]{16,}"), "<redacted-token>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "<redacted-slack-token>"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE), "Bearer <redacted>"),
    # Email — only the operator's own email (others stay)
    (re.compile(r"\bdszuber@gmail\.com\b", re.IGNORECASE), "<operator-email>"),
]


def sanitize(text: str) -> tuple[str, int]:
    """Apply all sanitize rules. Returns (cleaned_text, num_replacements)."""
    total = 0
    out = text
    for pat, repl in SANITIZE_RULES:
        out, n = pat.subn(repl, out)
        total += n
    return out, total


def is_denied_file(path: Path) -> bool:
    name = path.name
    return any(rx.search(name) for rx in DENY_FILES)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def _atomic_write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f"{p.suffix}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def discover_repos() -> list[Path]:
    """List repos under d:/APPS (top-level dirs)."""
    if not BASE.exists():
        return []
    out = []
    for p in BASE.iterdir():
        if not p.is_dir():
            continue
        if p.name in EXCLUDED_REPOS:
            continue
        # heuristic: actual repo if it has design/ OR .git OR CLAUDE.md
        if (p / "design").exists() or (p / ".git").exists() or (p / "CLAUDE.md").exists():
            out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def compile_memory(target: Path, sanitize_count: list[int]) -> None:
    """Combine ~/.claude/MEMORY.md + projects/<slug>/memory/MEMORY.md."""
    sections: list[str] = ["# MEMORY (compiled snapshot)\n",
                           f"_Generated: {datetime.utcnow().isoformat()}Z_\n"]

    global_mem = HOME / "MEMORY.md"
    if global_mem.exists():
        sections.append("## Global memory (`~/.claude/MEMORY.md`)\n")
        body, n = sanitize(_read(global_mem))
        sanitize_count[0] += n
        sections.append(body)

    proj_root = HOME / "projects"
    if proj_root.exists():
        sections.append("\n## Per-project memory\n")
        for proj in sorted(proj_root.iterdir()):
            mem_dir = proj / "memory"
            if not mem_dir.exists():
                continue
            sections.append(f"\n### `{proj.name}`\n")
            for mf in sorted(mem_dir.glob("*.md")):
                if is_denied_file(mf):
                    continue
                body, n = sanitize(_read(mf))
                sanitize_count[0] += n
                sections.append(f"\n#### `{mf.name}`\n")
                sections.append(body)

    _atomic_write(target / "MEMORY.md", "\n".join(sections))


def copy_simple(src: Path, dst: Path, sanitize_count: list[int]) -> bool:
    if not src.exists():
        return False
    body, n = sanitize(_read(src))
    sanitize_count[0] += n
    _atomic_write(dst, body)
    return True


def copy_visions(target_visions: Path, sanitize_count: list[int]) -> int:
    n_copied = 0
    for repo in discover_repos():
        vis_dir = repo / "design" / "visions"
        if not vis_dir.exists():
            continue
        for vf in vis_dir.glob("*.md"):
            if is_denied_file(vf):
                continue
            body, n = sanitize(_read(vf))
            sanitize_count[0] += n
            _atomic_write(target_visions / vf.name, body)
            n_copied += 1
    return n_copied


def copy_plans_recent(target_plans: Path, days: int, sanitize_count: list[int]) -> int:
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    date_re = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)\.md$")
    n_copied = 0
    for repo in discover_repos():
        plans_dir = repo / "design" / "plans"
        if not plans_dir.exists():
            continue
        for pf in plans_dir.glob("*.md"):
            if is_denied_file(pf):
                continue
            m = date_re.match(pf.name)
            if not m:
                continue
            try:
                pdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if pdate < cutoff:
                continue
            body, n = sanitize(_read(pf))
            sanitize_count[0] += n
            target_name = f"{repo.name.replace(' ', '_')}_{pf.name}"
            _atomic_write(target_plans / target_name, body)
            n_copied += 1
    return n_copied


def copy_idea_boxes(target_dir: Path, sanitize_count: list[int]) -> int:
    n_copied = 0
    for repo in discover_repos():
        ib = repo / "IDEA_BOX.md"
        if not ib.exists():
            continue
        body, n = sanitize(_read(ib))
        sanitize_count[0] += n
        slug = repo.name.lower().replace(" ", "-").replace(".", "-")
        _atomic_write(target_dir / f"{slug}.md", body)
        n_copied += 1
    return n_copied


def regen_local_catalogs() -> None:
    for script in ("plan_catalog.py", "vision_catalog.py"):
        p = HOME / "scripts" / script
        if not p.exists():
            continue
        try:
            subprocess.run(["python", str(p)], capture_output=True, timeout=60)
        except Exception:
            pass


def write_meta(target: Path, stats: dict) -> None:
    meta = {
        "schema_version": 1,
        "synced_at": datetime.utcnow().isoformat() + "Z",
        **stats,
    }
    _atomic_write(target / "_meta" / "last_synced.json",
                  json.dumps(meta, indent=2))


def git_commit_push(target: Path, note: str, push: bool) -> tuple[bool, str]:
    if not (target / ".git").exists():
        return False, "not a git repo (skip)"
    try:
        subprocess.run(["git", "add", "-A"], cwd=target, check=True,
                       capture_output=True, timeout=30)
        # Only commit if changes
        r = subprocess.run(["git", "status", "--porcelain"], cwd=target,
                           capture_output=True, text=True, timeout=10)
        if not r.stdout.strip():
            return True, "no changes"
        msg = f"sync: {note or datetime.utcnow().isoformat()}"
        subprocess.run(["git", "commit", "-m", msg], cwd=target, check=True,
                       capture_output=True, timeout=30)
        if push:
            subprocess.run(["git", "push"], cwd=target, check=True,
                           capture_output=True, timeout=60)
        return True, msg
    except subprocess.CalledProcessError as e:
        return False, (e.stderr.decode() if e.stderr else str(e))[:300]
    except Exception as e:
        return False, str(e)[:300]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ecosystem context to private repo")
    parser.add_argument("--target", default="D:/dotclaude/ecosystem-context",
                        help="Target context repo path")
    parser.add_argument("--days", type=int, default=30,
                        help="Plan recency window in days (default 30)")
    parser.add_argument("--push", action="store_true", help="git commit + push after sync")
    parser.add_argument("--note", default="", help="Commit message note")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write — print stats only")
    parser.add_argument("--skip-catalog-regen", action="store_true",
                        help="Skip running plan_catalog.py / vision_catalog.py")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        print(f"ERROR: target dir does not exist: {target}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[DRY RUN] target = {target}")
        print(f"[DRY RUN] repos discovered = {[r.name for r in discover_repos()]}")
        return 0

    if not args.skip_catalog_regen:
        regen_local_catalogs()

    sanitize_count = [0]

    # Compile memory
    compile_memory(target, sanitize_count)

    # Copy global indexes
    copied_global = 0
    for src_name, dst_name in [
        ("PLANS.md", "PLANS.md"),
        ("VISIONS.md", "VISIONS.md"),
        ("ECOSYSTEM_IDEA_BOX.md", "ECOSYSTEM_IDEA_BOX.md"),
    ]:
        if copy_simple(HOME / src_name, target / dst_name, sanitize_count):
            copied_global += 1

    # Copy visions, plans, idea_boxes
    visions_dir = target / "visions"
    visions_dir.mkdir(parents=True, exist_ok=True)
    n_visions = copy_visions(visions_dir, sanitize_count)

    plans_dir = target / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    n_plans = copy_plans_recent(plans_dir, args.days, sanitize_count)

    idea_dir = target / "idea_boxes"
    idea_dir.mkdir(parents=True, exist_ok=True)
    n_ideas = copy_idea_boxes(idea_dir, sanitize_count)

    # Meta
    stats = {
        "global_files_copied": copied_global,
        "visions_copied": n_visions,
        "plans_copied": n_plans,
        "idea_boxes_copied": n_ideas,
        "sanitize_replacements": sanitize_count[0],
        "days_window": args.days,
    }
    write_meta(target, stats)

    # Commit/push
    pushed = ""
    if args.push:
        ok, msg = git_commit_push(target, args.note, push=True)
        pushed = f" | git {'OK' if ok else 'FAIL'}: {msg}"

    print(f"sync: visions={n_visions} plans={n_plans} ideas={n_ideas} "
          f"global={copied_global} sanitize_repl={sanitize_count[0]}{pushed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
