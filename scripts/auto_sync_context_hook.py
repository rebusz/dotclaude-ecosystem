#!/usr/bin/env python3
"""PostToolUse hook — debounced auto-sync to ecosystem-context.

Fires when Write/Edit touches ~/.claude/MEMORY.md or ~/.claude/projects/*/memory/*.md.
Debounced: skips if last sync was <5 min ago. Runs in background — never blocks the tool call.

Fail silently — sync issues are not session-blocking.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home() / ".claude"
TARGET = Path("D:/dotclaude/ecosystem-context")
STATE_FILE = HOME / ".auto_sync_context_state.json"
DEBOUNCE_SECONDS = 300  # 5 min

WATCHED_PATTERNS = [
    "/.claude/MEMORY.md",
    "/.claude/ECOSYSTEM_IDEA_BOX.md",
    "/.claude/projects/",  # any per-project memory
]


def _normalize(p: str) -> str:
    return p.replace("\\", "/").lower()


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return

    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        return

    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return
    norm = _normalize(file_path)

    if not any(p.lower() in norm for p in WATCHED_PATTERNS):
        return

    # Don't sync edits to the target repo itself (prevents loops)
    target_norm = _normalize(str(TARGET))
    if target_norm in norm:
        return

    # Debounce
    now = time.time()
    last_sync = 0.0
    if STATE_FILE.exists():
        try:
            last_sync = float(json.loads(STATE_FILE.read_text()).get("last_sync", 0))
        except Exception:
            pass
    if now - last_sync < DEBOUNCE_SECONDS:
        return

    if not TARGET.exists():
        return

    sync_script = HOME / "scripts" / "sync_ecosystem_context.py"
    if not sync_script.exists():
        return

    # Fire-and-forget background sync
    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        log_path = HOME / ".auto_sync_context.log"
        with log_path.open("a", encoding="utf-8") as logf:
            logf.write(f"\n--- auto-sync triggered at {time.ctime(now)} (file: {file_path}) ---\n")
            subprocess.Popen(
                ["python", str(sync_script),
                 "--target", str(TARGET),
                 "--push",
                 "--note", f"auto: memory edit {Path(file_path).name}",
                 "--skip-catalog-regen"],
                stdout=logf, stderr=logf, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

        # Update debounce state immediately so next hook fires don't double-trigger
        STATE_FILE.write_text(json.dumps({"last_sync": now}), encoding="utf-8")
    except Exception:
        return


if __name__ == "__main__":
    main()
