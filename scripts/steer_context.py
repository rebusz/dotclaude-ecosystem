#!/usr/bin/env python3
"""Steering context — thin augmenter over plan_context_loader for /whatnext.

Composes the EXISTING ``plan_context_loader`` (vision Why+DoD + IDEA_BOX + PLANS,
emitted as TEXT) and adds only the genuine new signal a "what next?" needs:

  - the income NORTH STAR (the primary vision's ``## North Star`` block — the
    prioritization lens every steering pass weighs tracks against),
  - per-repo recent git activity + recent plan slugs (the activity signal),
  - a heuristic coverage / drift map (DoD aspect x recent activity -> under-served?),
    explicitly LOW-CONFIDENCE so a fuzzy keyword match never hard-asserts drift.

Design intent (see plans/2026-06-20_meta_supervision_whatnext_system.md):
this is a THIN delta on the loader, NOT a new orchestration layer — it does not
re-implement vision/idea/plan parsing the loader already does; it shells the
loader and embeds its block.

Pure read-only. Fail-open: never raises; missing pieces degrade to notes.
Emits one markdown block wrapped in ``<steer-context>...</steer-context>`` in the
same spirit as the loader's ``<plan-context>``.

Usage:
    python steer_context.py --cwd "D:/APPS/TSU"
    python steer_context.py --cwd "$PWD" --days 7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home() / ".claude"
BASE = Path("d:/APPS")
LOADER = HOME / "scripts" / "plan_context_loader.py"
VISION_INDEX = HOME / ".vision_index.json"

# The income north-star lives as a `## North Star` block in this vision
# (operator decision 2026-06-20: one source of truth).
PRIMARY_VISION_SLUG = "tsu-execution-authority"

# Repos whose recent activity is the steering signal. The cwd repo is added at
# runtime; non-existent paths are skipped. Bounded on purpose (hook budget).
DEFAULT_ACTIVITY_REPOS = [
    BASE / "TSU",
    BASE / "Tsignal 5.0",
    BASE / "WatchF",
    BASE / "Obsidian Flow",
    BASE / "TsignalLAB",
]

DEFAULT_DAYS = 7
# Below this much activity the coverage map is not trustworthy enough to assert
# drift — we down-grade every gap to a "candidate, verify" rather than a fact.
MIN_SIGNAL = 3

_STOPWORDS = {
    "is", "are", "be", "the", "a", "an", "and", "or", "to", "of", "in", "on",
    "by", "with", "no", "not", "never", "all", "one", "every", "then", "into",
    "gets", "get", "from", "for", "its", "it", "so", "can", "must", "always",
    "each", "until", "this", "that", "as", "at", "up", "out", "via",
}


# ── reads ───────────────────────────────────────────────────────────────────

def _read_text(p: Path, limit_lines: int | None = None) -> str:
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
        if limit_lines:
            return "\n".join(text.splitlines()[:limit_lines])
        return text
    except Exception:
        return ""


def _detect_repo(cwd: Path) -> Path | None:
    """Walk up from cwd to find a repo root directly under d:/APPS."""
    try:
        cwd = cwd.resolve()
    except Exception:
        return None
    for parent in [cwd, *cwd.parents]:
        try:
            if parent.parent.resolve() == BASE.resolve():
                return parent
        except Exception:
            continue
    return None


def _extract_section(text: str, header: str) -> str:
    """Body under a ``## Header`` until the next ``## ``. Loader-compatible."""
    out: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.strip().lower() == header.lower():
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            out.append(line)
    return "\n".join(out).strip()


def _load_vision_index() -> dict:
    try:
        data = json.loads(VISION_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _find_primary_vision(repo_root: Path | None) -> Path | None:
    """Locate the north-star vision file: index first, then a bounded glob."""
    visions = _load_vision_index().get("visions", {})
    item = visions.get(PRIMARY_VISION_SLUG) if isinstance(visions, dict) else None
    if item and item.get("path"):
        p = Path(item["path"])
        if p.exists():
            return p
    if repo_root:
        cand = repo_root / "design" / "visions" / f"{PRIMARY_VISION_SLUG}.md"
        if cand.exists():
            return cand
    try:
        for hit in BASE.glob(f"*/design/visions/{PRIMARY_VISION_SLUG}.md"):
            return hit
    except Exception:
        pass
    return None


def _goal_memory_fallback() -> str:
    """First paragraph of the income-goal memory, if the vision has no block yet."""
    try:
        for mf in (HOME / "projects").glob("*/memory/tsu-goal-is-income-not-hobby.md"):
            text = _read_text(mf)
            body = text.split("---", 2)[-1] if text.startswith("---") else text
            for para in body.strip().split("\n\n"):
                if para.strip():
                    return para.strip()
    except Exception:
        pass
    return ""


# ── heuristic (the risky part — kept pure + tested) ─────────────────────────

def _derive_keywords(title: str) -> set[str]:
    """Content words (>=4 chars, non-stopword) from a DoD aspect title."""
    words = re.findall(r"[A-Za-z0-9-]+", title.lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


def _dod_aspects(vision_text: str) -> list[tuple[str, set[str]]]:
    """Extract ``- **Title.**`` bullets from the vision's Definition of Done."""
    dod = _extract_section(vision_text, "## Definition of Done")
    aspects: list[tuple[str, set[str]]] = []
    for line in dod.splitlines():
        m = re.match(r"\s*-\s+\*\*(.+?)\*\*", line)
        if not m:
            continue
        title = m.group(1).strip().rstrip(".")
        kws = _derive_keywords(title)
        if kws:
            aspects.append((title, kws))
    return aspects


def _coverage(aspects: list[tuple[str, set[str]]], corpus: list[str]) -> list[dict]:
    """Match each aspect's keywords against the activity corpus.

    Deliberately fuzzy (substring keyword match). The caller MUST present the
    result as low-confidence — a worked aspect whose commits used different
    words will show as a gap; that is a candidate to verify, not a fact.
    """
    corpus_l = [c.lower() for c in corpus]
    rows: list[dict] = []
    for title, kws in aspects:
        evidence = ""
        for c in corpus_l:
            if any(kw in c for kw in kws):
                evidence = c
                break
        rows.append({"aspect": title, "active": bool(evidence), "evidence": evidence})
    return rows


# ── activity ────────────────────────────────────────────────────────────────

def _git_recent(repo: Path, days: int) -> list[str]:
    if not (repo / ".git").exists():
        return []
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since={days} days ago",
             "--no-merges", "--pretty=%s", "-n", "60"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            return []
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


_PLAN_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)\.md$")


def _recent_plan_slugs(repos: list[Path], days: int) -> list[str]:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    slugs: list[str] = []
    plan_dirs = [r / "design" / "plans" for r in repos] + [HOME / "plans"]
    for pd in plan_dirs:
        if not pd.exists():
            continue
        try:
            for pf in pd.glob("*.md"):
                m = _PLAN_DATE_RE.match(pf.name)
                if not m:
                    continue
                try:
                    pdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                except ValueError:
                    continue
                if pdate >= cutoff:
                    slugs.append(m.group(2).replace("_", " ").replace("-", " "))
        except Exception:
            continue
    return slugs


def _loader_block(cwd: Path) -> str:
    """Embed plan_context_loader's text output (DRY — don't re-implement it)."""
    if not LOADER.exists():
        return "_(plan_context_loader.py not found — vision/IDEA_BOX/PLANS context unavailable)_"
    try:
        r = subprocess.run(
            ["python", str(LOADER), "--cwd", str(cwd), "--quiet-empty"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        return "_(plan_context_loader produced no output)_"
    except Exception as exc:  # noqa: BLE001 - fail-open
        return f"_(plan_context_loader failed: {type(exc).__name__})_"


# ── compose ─────────────────────────────────────────────────────────────────

def build(cwd: Path, days: int) -> str:
    repo_root = _detect_repo(cwd)

    repos: list[Path] = []
    for r in [*DEFAULT_ACTIVITY_REPOS, repo_root]:
        if r and r.exists() and r not in repos:
            repos.append(r)

    vision_path = _find_primary_vision(repo_root)
    vision_text = _read_text(vision_path) if vision_path else ""

    north_star = _extract_section(vision_text, "## North Star")
    if not north_star:
        fb = _goal_memory_fallback()
        north_star = (
            (fb + "\n\n_(north-star read from goal memory — the vision has no "
             "`## North Star` block yet)_") if fb
            else "_(no north-star found — add a `## North Star` block to the "
            f"`{PRIMARY_VISION_SLUG}` vision)_"
        )

    aspects = _dod_aspects(vision_text)

    commit_subjects: list[str] = []
    activity_by_repo: list[tuple[str, int]] = []
    for repo in repos:
        subjects = _git_recent(repo, days)
        if subjects:
            activity_by_repo.append((repo.name, len(subjects)))
        commit_subjects.extend(subjects)
    plan_slugs = _recent_plan_slugs(repos, days)
    corpus = commit_subjects + plan_slugs

    rows = _coverage(aspects, corpus)
    under = [r for r in rows if not r["active"]]
    insufficient = len(corpus) < MIN_SIGNAL or not aspects

    # ── render ──
    out: list[str] = []
    out.append(f'<steer-context cwd="{cwd.as_posix()}" repo="{repo_root.name if repo_root else "?"}" window="{days}d">')
    out.append("[steer] fired")  # dead != silent: proves the steer path ran
    out.append("_Auto-composed by steer_context.py — the raw material for a STEERING BRIEF._")
    out.append("")

    out.append("## North Star (income lens)")
    out.append(north_star)
    out.append("")
    out.append("_Prioritization lens for every track below: **does this slice move toward "
               "live-trading income, or is it polish?**_")
    out.append("")

    out.append(f"## Recent activity ({days}d signal)")
    if activity_by_repo:
        out.append("Commits per repo: "
                   + ", ".join(f"{name} ({n})" for name, n in activity_by_repo))
    else:
        out.append("_(no commits found in window across scanned repos)_")
    if plan_slugs:
        uniq_slugs = list(dict.fromkeys(plan_slugs))
        out.append("Recent plan slugs: " + "; ".join(uniq_slugs[:12]))
    out.append("")

    out.append("## Coverage map (DoD aspect x recent activity) — HEURISTIC, LOW-CONFIDENCE")
    if not aspects:
        out.append(f"_(could not read DoD aspects from the `{PRIMARY_VISION_SLUG}` vision — "
                   "coverage map unavailable)_")
    else:
        out.append("| DoD aspect | Recent activity? | evidence (matched commit/plan) |")
        out.append("|---|---|---|")
        for r in rows:
            mark = "yes" if r["active"] else "**no — candidate gap**"
            ev = (r["evidence"][:60] + "…") if len(r["evidence"]) > 60 else (r["evidence"] or "—")
            out.append(f"| {r['aspect']} | {mark} | {ev} |")
        out.append("")
        if insufficient:
            out.append("> **insufficient-signal:** activity corpus is sparse — treat EVERY gap "
                       "above as a *candidate to verify*, not a confirmed drift. Keyword matching "
                       "also mis-flags worked aspects whose commits used other words.")
        else:
            out.append("> **confidence: heuristic** (keyword substring match). A gap means *no "
                       "keyword hit*, not proven neglect — sanity-check against your own memory "
                       "before steering. False gaps misdirect steering.")
        if under and not insufficient:
            out.append("")
            out.append("**Candidate under-served aspects:** "
                       + "; ".join(r["aspect"] for r in under))
    out.append("")

    out.append("## Loaded plan context (vision Why+DoD / IDEA_BOX / PLANS)")
    out.append(_loader_block(cwd))
    out.append("")

    out.append("## How to use (steering brief)")
    out.append("1. Restate the **north-star line** + the single nearest milestone to live-trading.")
    out.append("2. Present the coverage map; flag under-served aspects (respect the confidence note).")
    out.append("3. Propose **2-4 parallel tracks spanning DIFFERENT aspects** (don't tunnel). Each "
               "track = `{aspect, slice, risk R0-R3, difficulty V0-V10, executor}`.")
    out.append("4. Route by difficulty: **V0-V3** Cursor Composer / VS Code OK · **V4-V6** Claude "
               "Code / Codex · **V7-V10** Claude Code (opus) / careful Codex — **never Composer >V3**.")
    out.append("5. Pick **one first domino** (usually the income-nearest unblocked track) + why.")
    out.append("6. Never invent a backlog — every track traces to a vision DoD bullet, a PLANS entry, "
               "or an IDEA_BOX row above.")
    out.append("</steer-context>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Steering context (thin augmenter for /whatnext)")
    parser.add_argument("--cwd", help="Working directory (defaults to $PWD)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Activity window in days (default {DEFAULT_DAYS})")
    args = parser.parse_args()

    cwd = Path(args.cwd or os.getcwd())
    try:
        cwd = cwd.resolve()
    except Exception:
        pass

    try:
        print(build(cwd, max(1, args.days)))
    except Exception as exc:  # noqa: BLE001 - fail-open, never break a prompt
        print("<steer-context>\n[steer] fired\n_(steer_context error: "
              f"{type(exc).__name__})_\n</steer-context>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
