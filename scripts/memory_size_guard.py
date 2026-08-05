#!/usr/bin/env python3
"""Stop-hook: proactive memory-index size guard (hot/cold discipline).

Read-only, throttled, fail-silent. NEVER edits, moves, or deletes memory — it
only DETECTS when a project's hot MEMORY.md index is creeping toward the auto-load
cap and NUDGES to archive finished entries. Mutation stays a deliberate in-session
action (safe against concurrent sessions writing the same memory dir).

Companion to the hot/cold split: MEMORY.md (hot, auto-loaded) vs ARCHIVE.md (cold,
on-demand). Fires EARLY (well before the ~24KB cap where over-cap lines get dropped
from context) so there is time to act. Registered as a Stop hook in settings.json.
"""
import json
import pathlib
import re
import time

WARN_BYTES = 18_000          # nudge above this (hard auto-load cap is ~24.4KB)
THROTTLE_SECONDS = 3 * 3600  # at most one nudge per index every 3h
STATE_DIR = pathlib.Path.home() / ".claude" / "state"
STATE_FILE = STATE_DIR / "memory_size_guard.json"
PROJECTS = pathlib.Path.home() / ".claude" / "projects"
# Strong "finished" markers that signal a hot entry is archivable.
DONE_RE = re.compile(r"\b(DONE|SHIPPED|CLOSED|COMPLETE|ABANDONED|SUPERSEDED)\b")


def main():
    if not PROJECTS.is_dir():
        return
    now = time.time()
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}

    nudges = []
    for mem in PROJECTS.glob("*/memory/MEMORY.md"):
        try:
            size = mem.stat().st_size
        except Exception:
            continue
        if size < WARN_BYTES:
            continue
        key = str(mem)
        if now - float(state.get(key, 0)) < THROTTLE_SECONDS:
            continue
        # count archivable hot entries
        archivable = 0
        try:
            for line in mem.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("- [") and DONE_RE.search(line):
                    archivable += 1
        except Exception:
            pass
        slug = mem.parent.parent.name
        nudges.append((slug, size, archivable))
        state[key] = now

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass

    for slug, size, archivable in nudges:
        kb = size / 1024.0
        tail = (
            "{0} hot entries look archivable (DONE/SHIPPED/CLOSED/...)".format(archivable)
            if archivable
            else "no obvious DONE entries — trim verbose hooks instead"
        )
        print(
            "[memory-hygiene] {0} MEMORY.md is {1:.1f}KB (nearing the ~24KB auto-load cap; "
            "over-cap lines get dropped from context). {2}. Move them to ARCHIVE.md or run "
            "/consolidate-memory per the retirement policy in MEMORY.md's header.".format(
                slug, kb, tail
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never disrupt the session
