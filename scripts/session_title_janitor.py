#!/usr/bin/env python
"""Normalize CCD session titles to `<Repo> <DD MON> [chip] <topic>`.

The `mcp__ccd_session_mgmt__set_session_title` tool silently refuses to
overwrite any session whose `titleSource` is `user`, and still returns a
success-shaped message. Operator rule (2026-07-25): the janitor must stamp a
date on EVERY session title, including ones renamed by hand. So this script
edits the session store on disk instead of going through the MCP tool.

Minimal-edit policy: the operator's own wording is preserved verbatim. The only
change is injecting `<DD MON>` after the leading repo token (or prefixing
`<Repo> <DD MON>` when no repo token is present).

Usage:
    python session_title_janitor.py            # dry run, prints planned renames
    python session_title_janitor.py --apply    # write changes
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import tempfile
import time

def store_globs() -> list[str]:
    """Session-store locations, most authoritative first.

    CCD ships as an MSIX package, so its writes to `%APPDATA%\\Claude` are
    redirected into the package's private LocalCache. Anything CCD launched
    inherits the package identity and sees a merged view at the classic path,
    which is why a hand-run janitor works. The Windows scheduled task runs
    OUTSIDE that identity and sees only the real filesystem, where the classic
    path does not exist at all — measured 2026-08-03: `rootExists=False`,
    0 files, so every scheduled run was a silent no-op.

    The package path is correct from both contexts, so it wins.
    """
    roots = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.extend(sorted(glob.glob(os.path.join(
            local, "Packages", "Claude_*", "LocalCache", "Roaming",
            "Claude", "claude-code-sessions"))))
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(os.path.join(appdata, "Claude", "claude-code-sessions"))
    return [os.path.join(r, "*", "*", "local_*.json") for r in roots]

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Already-conforming titles carry `<DD MON>` as the token right after the repo.
DATE_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b")

# Operator shorthands seen in hand-written titles, mapped to their repo dir.
ALIASES = {
    "Obsidian Flow": ["OF", "Obsidian flow"],
    "TsignalLAB": ["LAB", "Tsignal LAB"],
    "Hue Flow": ["HUE"],
    "ViF": ["VIF"],
    "VAVO website": ["VAVO"],
    "Tsignal 5.0": ["Tsignal"],
    "Tsignal Remote": ["Tsignal remote"],
}

# Noise tokens the operator uses as a second-position marker, not part of topic.
MARKERS = {"MASTER", "INV", "GLOBAL"}


def force_utf8_stdio() -> None:
    """Session titles are Polish/emoji-heavy; a cp1252 console must not kill the run.

    The scheduled runner exports PYTHONIOENCODING, but a manual run inherits the
    legacy console codepage and died mid-listing on the first `l` with a stroke —
    in `--apply` that aborts every session after the offending title.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (AttributeError, ValueError, OSError):
                pass


def repo_from_cwd(cwd: str) -> str | None:
    """`D:\\APPS\\Tsignal 5.0\\.claude\\worktrees\\x` -> `Tsignal`."""
    if not cwd:
        return None
    parts = re.split(r"[\\/]+", cwd)
    for i, p in enumerate(parts):
        if p.upper() == "APPS" and i + 1 < len(parts):
            raw = parts[i + 1]
            return re.sub(r"\s+\d+(\.\d+)*$", "", raw)  # strip " 5.0"
    if "dotclaude" in cwd:
        return "dotclaude"
    return None


def accepted_prefixes(repo: str, raw_dir: str | None) -> list[str]:
    """Prefixes that already identify the repo, longest first.

    Also accepts any leading word of the repo name (`Garmin` for `Garmin
    Flow`), so a title the operator already prefixed is not double-prefixed.
    """
    out = {repo}
    for key, aliases in ALIASES.items():
        canon = re.sub(r"\s+\d+(\.\d+)*$", "", key)
        if canon == repo or key == raw_dir:
            out.add(canon)
            out.update(aliases)
    words = repo.split()
    for i in range(1, len(words)):
        out.add(" ".join(words[:i]))
    return sorted(out, key=len, reverse=True)


def decap(text: str) -> str:
    """Lowercase the first letter, but never mangle acronyms or CamelCase."""
    head = text.split(" ", 1)[0]
    if head.isupper() or not head[1:].islower():
        return text
    return text[0].lower() + text[1:]


def date_token(session: dict) -> str:
    ms = session.get("createdAt") or session.get("lastActivityAt")
    if not ms:
        return ""
    d = dt.datetime.fromtimestamp(ms / 1000)
    return f"{d.day:02d} {MONTHS[d.month - 1]}"


def normalize(title: str, repo: str, raw_dir: str | None, date: str) -> str | None:
    """Return the conforming title, or None when no change is needed."""
    title = (title or "").strip()
    if not title or not date:
        return None

    for prefix in accepted_prefixes(repo, raw_dir):
        if title.lower().startswith(prefix.lower()):
            # Keep the operator's own spelling of the prefix, not our canonical
            # form — `ViF` must not become `VIF`.
            kept = title[: len(prefix)]
            rest = title[len(prefix):].lstrip()
            # Already dated in the slot right after the repo token?
            if DATE_RE.match(rest):
                return None
            head, _, tail = rest.partition(" ")
            if head.upper() in MARKERS and tail.strip():
                rest = tail.lstrip()
            if not rest:
                return None
            return f"{kept} {date} {decap(rest)}"

    # No repo token at all — prefix repo + date, keep the topic verbatim.
    if DATE_RE.search(title[:20]):
        return None
    return f"{repo} {date} {decap(title)}"


def atomic_write(path: str, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> int:
    force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--limit", type=int, default=0,
                    help="only touch the N most recently active sessions")
    ap.add_argument("--skip-active-hours", type=float, default=6.0,
                    help="leave alone sessions touched within N hours; the "
                         "running app flushes its in-memory title over those. "
                         "0 sweeps everything (safe only with CCD closed).")
    args = ap.parse_args()

    candidates = store_globs()
    paths: list[str] = []
    store_used = ""
    for pattern in candidates:
        paths = glob.glob(pattern)
        if paths:
            store_used = pattern
            break
    if not paths:
        print("no session store found; tried:\n  " + "\n  ".join(candidates),
              file=sys.stderr)
        return 1
    print(f"store: {store_used}")

    sessions = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if d.get("sessionId") and not d.get("isArchived"):
            sessions.append((p, d))

    sessions.sort(key=lambda t: t[1].get("lastActivityAt") or 0, reverse=True)
    if args.limit:
        sessions = sessions[: args.limit]

    changed = 0
    skipped_hot = 0
    cutoff_ms = (time.time() - args.skip_active_hours * 3600) * 1000
    for path, d in sessions:
        # A session CCD currently holds in memory gets its old title flushed
        # back within minutes (2026-07-25: 13 of 21 renames reverted). Cold
        # sessions are never rewritten, so those stamps stick.
        #
        # Judge hotness by `lastActivityAt` (CCD owns it) and NOT by file
        # mtime: our own rename bumps mtime, which made every session we just
        # stamped look hot for the next 6h and would defer re-stamping a title
        # the app did revert.
        if args.skip_active_hours:
            last = d.get("lastActivityAt")
            if last is None:
                try:
                    last = os.path.getmtime(path) * 1000
                except OSError:
                    last = 0
            if last > cutoff_ms:
                skipped_hot += 1
                continue
        raw_dir = None
        cwd = d.get("cwd") or ""
        parts = re.split(r"[\\/]+", cwd)
        for i, p in enumerate(parts):
            if p.upper() == "APPS" and i + 1 < len(parts):
                raw_dir = parts[i + 1]
        repo = repo_from_cwd(cwd)
        if not repo:
            continue
        new = normalize(d.get("title", ""), repo, raw_dir, date_token(d))
        if not new or new == d.get("title"):
            continue
        changed += 1
        print(f"{'RENAME' if args.apply else 'WOULD'}: {d['title']!r} -> {new!r}")
        if args.apply:
            d["title"] = new  # titleSource intentionally left as-is
            atomic_write(path, d)

    print(f"\n{len(sessions)} sessions checked, {changed} "
          f"{'renamed' if args.apply else 'would be renamed'}"
          f", {skipped_hot} skipped as hot")
    if args.apply and changed:
        print("NOTE: the CCD app caches titles in memory; restart it to see "
              "the new titles in the sidebar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
