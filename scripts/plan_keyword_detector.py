#!/usr/bin/env python3
"""UserPromptSubmit hook — detect plan/module-creation keywords and inject context.

When user prompt contains keywords like "nowy plan", "new plan", "tworzymy",
"design module", "create module", we run plan_context_loader.py and emit its
output as additional context for AI.

Triggers ONLY on plan/module creation phrases — NOT on general talk about plans.
Best-effort: never fails the prompt; on error, exits silently.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home() / ".claude"
LOADER = HOME / "scripts" / "plan_context_loader.py"

PATTERNS = [
    r"\bnow[ay]\s+plan\b",
    r"\btworzymy\s+plan\b",
    r"\bzr[oó]b(my)?\s+plan\b",
    r"\bnowy\s+modu[lł]\b",
    r"\btworzymy\s+modu[lł]\b",
    r"\bnew\s+plan\b",
    r"\bcreate\s+plan\b",
    r"\bdesign\s+plan\b",
    r"\bnew\s+module\b",
    r"\bcreate\s+module\b",
    r"\bdesign\s+module\b",
    r"\bmode\s+architect\b",
    r"\btryb\s+architect\b",
    r"/plan-ceo-review\b",
    r"/plan-eng-review\b",
    r"/plan-design-review\b",
    r"/autoplan\b",
    r"/plan-tune\b",
]
COMPILED = [re.compile(p, re.IGNORECASE) for p in PATTERNS]


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    prompt = data.get("prompt", "") or ""
    if not prompt:
        return 0

    if not any(rx.search(prompt) for rx in COMPILED):
        return 0

    cwd = data.get("cwd") or os.getcwd()

    if not LOADER.exists():
        return 0

    try:
        r = subprocess.run(
            ["python", str(LOADER), "--cwd", cwd, "--quiet-empty"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            print("=== AUTO-INJECTED PLAN CONTEXT (keyword trigger) ===")
            print(r.stdout)
            print("=== END AUTO-INJECTED PLAN CONTEXT ===")
            print("AI: read the context block above before designing the plan/module.")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
