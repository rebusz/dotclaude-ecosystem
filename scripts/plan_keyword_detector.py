#!/usr/bin/env python3
"""UserPromptSubmit hook — detect plan/module + steering keywords, inject context.

Two independent triggers, one prompt-router (extend, don't fork — this is the
single live UserPromptSubmit hook, wired in settings.json with matcher:"*"):

  * PLAN/MODULE creation phrases ("nowy plan", "new plan", "mode architect", …)
    -> run plan_context_loader.py and inject the <plan-context> block.
  * STEERING phrases ("what next", "co dalej", "priorytety", "drift", …)
    -> run steer_context.py and inject the <steer-context> block so a plain
       "co dalej?" ALWAYS loads goals + vision + coverage, with no mode trigger.
       (This is the fix for "asking what-next doesn't fire": the harness runs
       hooks deterministically; memory/CLAUDE.md do not self-enforce.)

Best-effort: never fails the prompt; on any error, exits silently (return 0).
Non-matching prompts add ZERO tokens.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Emit utf-8 so injected Polish / em-dashes survive (the harness reads utf-8).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path.home() / ".claude"
LOADER = HOME / "scripts" / "plan_context_loader.py"
STEER = HOME / "scripts" / "steer_context.py"

# Plan/module CREATION — narrow on purpose (not general talk about plans).
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

# STEERING / "what next" — operator-specified set (2026-06-20) + obvious variants.
STEER_PATTERNS = [
    r"\bwhat\s*next\b",
    r"\bco\s+dalej\b",
    r"\bco\s+teraz\b",
    r"\bpriorytet(y|[oó]w)?\b",
    r"\bpriorities\b",
    r"\bdrift\b",
    r"\bare\s+we\s+drifting\b",
    r"\bbig\s+picture\b",
    r"\bfull\s+picture\b",
    r"/whatnext\b",
]
STEER_COMPILED = [re.compile(p, re.IGNORECASE) for p in STEER_PATTERNS]

_STEER_INSTRUCTION = (
    'AI: you were asked "what next / co dalej / priorytety". Produce a STEERING '
    "BRIEF from the steering context above (or run the /whatnext skill): north-star "
    "line + coverage map + drift flags + 2-4 PARALLEL tracks spanning DIFFERENT "
    "aspects, each {aspect, slice, risk R0-R3, difficulty V0-V10, executor}. Route by "
    "V-scale (V0-V3 Composer/VS Code; V4-V6 Claude/Codex; V7-V10 Claude opus/careful "
    "Codex; never Composer >V3). Do NOT invent a next step — ground every track in the "
    "vision DoD / PLANS / IDEA_BOX above. Respect the coverage map's confidence note."
)


def _emit_plan(cwd: str) -> None:
    if not LOADER.exists():
        return
    try:
        r = subprocess.run(
            ["python", str(LOADER), "--cwd", cwd, "--quiet-empty"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            print("=== AUTO-INJECTED PLAN CONTEXT (keyword trigger) ===")
            print(r.stdout)
            print("=== END AUTO-INJECTED PLAN CONTEXT ===")
            print("AI: read the context block above before designing the plan/module.")
    except Exception:
        return


def _emit_steer(cwd: str) -> None:
    # Always print the marker: a broken steer path must be visibly DEAD, never
    # SILENT (the whole point of this system is fixing a silent no-fire).
    print("=== AUTO-INJECTED STEERING CONTEXT (what-next trigger) ===")
    if STEER.exists():
        try:
            r = subprocess.run(
                ["python", str(STEER), "--cwd", cwd],
                capture_output=True, text=True, timeout=14,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0 and r.stdout.strip():
                print(r.stdout.strip())
            else:
                print("[steer] fired — steer_context produced no output")
        except Exception:
            print("[steer] fired — steer_context error (fail-open)")
    else:
        print("[steer] fired — steer_context.py not found")
    print("=== END AUTO-INJECTED STEERING CONTEXT ===")
    print(_STEER_INSTRUCTION)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if raw and ord(raw[0]) == 0xFEFF:  # strip a leading BOM some shells prepend
            raw = raw[1:]
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    prompt = data.get("prompt", "") or ""
    if not prompt:
        return 0

    plan_match = any(rx.search(prompt) for rx in COMPILED)
    steer_match = any(rx.search(prompt) for rx in STEER_COMPILED)
    if not (plan_match or steer_match):
        return 0  # non-matching prompts add ZERO tokens

    cwd = data.get("cwd") or os.getcwd()

    # Steer is a superset (it already embeds the loader block), so when a prompt
    # trips both, the steer branch covers the plan context too — avoid double-load.
    if steer_match:
        _emit_steer(cwd)
    elif plan_match:
        _emit_plan(cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
