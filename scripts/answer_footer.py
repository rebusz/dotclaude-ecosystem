#!/usr/bin/env python3
"""Stop hook — print one-line answer footer to the conversation transcript.

Format:
    HH:MM:SS · Mon DD · MODEL · DIR/BRANCH · turn N · IN↑/OUT↓ tok · $X.XX sess

Source of every field is the hook input JSON on stdin or local files (no LLM
calls, no network). Per-session turn counter persists at
~/.claude/state/turn_counter_<session_id>. Model name and cost are derived
from the transcript JSONL Claude Code maintains (Stop hook input does not
include the model field, and cost_usd is not stored — computed from usage).

Output: a JSON object with `systemMessage` so Claude Code prints the line into
the transcript. Fail silently — never break the session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "state"

# Pricing table: (input, output, cache_creation, cache_read) per 1M tokens, USD.
# cache_creation = 1.25x input (5-minute TTL); cache_read = 0.10x input.
# Verified against the claude-api skill's model catalog on 2026-07-25. The prior
# table carried Opus 3 / 4.0 era rates (15/75) for the whole Opus 4.x line and
# had no Claude 5 entry at all, so every Opus turn was mispriced.
# Sonnet 5 list price is used; its $2/$10 introductory rate runs through
# 2026-08-31, so the footer over-reports slightly until then and self-corrects.
_PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5":       (10.0,  50.0,  12.50, 1.00),
    "claude-mythos-5":      (10.0,  50.0,  12.50, 1.00),
    "claude-opus-5":        (5.0,   25.0,   6.25, 0.50),
    "claude-opus-4-8":      (5.0,   25.0,   6.25, 0.50),
    "claude-opus-4-7":      (5.0,   25.0,   6.25, 0.50),
    "claude-opus-4-6":      (5.0,   25.0,   6.25, 0.50),
    "claude-opus-4-5":      (5.0,   25.0,   6.25, 0.50),
    "claude-sonnet-5":      (3.0,   15.0,   3.75, 0.30),
    "claude-sonnet-4-6":    (3.0,   15.0,   3.75, 0.30),
    "claude-sonnet-4-5":    (3.0,   15.0,   3.75, 0.30),
    "claude-haiku-4-5":     (1.0,    5.0,   1.25, 0.10),
}
# Fallback for an unrecognised model id. Deliberately the most expensive current
# tier: a silent cheap fallback (the old behaviour) under-reported real spend,
# and the footer flags the estimate as uncertain rather than hiding the gap.
_DEFAULT_PRICING = (10.0, 50.0, 12.50, 1.00)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _short_model(model: str) -> str:
    m = (model or "").lower()
    if not m:
        return "?"
    if "fable" in m:
        return "FABLE-5"
    if "mythos" in m:
        return "MYTHOS-5"
    if "opus-5" in m:
        return "OPUS-5"
    if "opus" in m and "4-8" in m:
        return "OPUS-4.8"
    if "opus" in m and "4-7" in m:
        return "OPUS-4.7"
    if "opus" in m and "4-6" in m:
        return "OPUS-4.6"
    if "opus" in m:
        return "OPUS"
    if "sonnet-5" in m:
        return "SONNET-5"
    if "sonnet" in m and "4-6" in m:
        return "SONNET-4.6"
    if "sonnet" in m:
        return "SONNET"
    if "haiku" in m and "4-5" in m:
        return "HAIKU-4.5"
    if "haiku" in m:
        return "HAIKU"
    return model.split("/")[-1].upper()


def _calc_turn_cost(model: str, in_tok: int, out_tok: int, cc_tok: int, cr_tok: int) -> float:
    pricing = _PRICING.get(model.lower(), _DEFAULT_PRICING)
    inp_p, out_p, cc_p, cr_p = pricing
    return (
        in_tok  * inp_p / 1_000_000
        + out_tok * out_p / 1_000_000
        + cc_tok  * cc_p  / 1_000_000
        + cr_tok  * cr_p  / 1_000_000
    )


def _git_branch(cwd: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        return None
    return None


def _bump_turn_counter(session_id: str) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = STATE_DIR / f"turn_counter_{session_id}"
    n = 0
    if f.exists():
        try:
            n = int(f.read_text().strip() or "0")
        except Exception:
            n = 0
    n += 1
    tmp = f.with_suffix(".tmp")
    tmp.write_text(str(n))
    tmp.replace(f)
    return n


def _parse_transcript(path: str) -> tuple[int, int, float, str, bool]:
    """Return (in_tokens, out_tokens, session_cost_usd, model, priced_ok).

    `priced_ok` is False when any turn used a model id absent from _PRICING, so
    the footer can flag the total as an estimate instead of quoting a confident
    number derived from a fallback rate.

    Walks the JSONL transcript:
      - accumulates cost from every assistant turn's usage data + pricing table
      - last assistant message → this-turn tokens and model name
    """
    in_tok = out_tok = 0
    session_cost = 0.0
    last_usage: dict | None = None
    last_model = ""
    priced_ok = True

    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                if rec.get("type") == "assistant":
                    msg = rec.get("message") or {}
                    if not isinstance(msg, dict):
                        continue
                    turn_model = msg.get("model") or last_model
                    if turn_model:
                        last_model = turn_model
                    usage = msg.get("usage")
                    if isinstance(usage, dict):
                        last_usage = usage
                        if (turn_model or "").lower() not in _PRICING:
                            priced_ok = False
                        it = int(usage.get("input_tokens") or 0)
                        ot = int(usage.get("output_tokens") or 0)
                        cc = int(usage.get("cache_creation_input_tokens") or 0)
                        cr = int(usage.get("cache_read_input_tokens") or 0)
                        session_cost += _calc_turn_cost(turn_model, it, ot, cc, cr)
    except Exception:
        return 0, 0, 0.0, "", False

    if isinstance(last_usage, dict):
        in_tok = int(
            (last_usage.get("input_tokens") or 0)
            + (last_usage.get("cache_read_input_tokens") or 0)
            + (last_usage.get("cache_creation_input_tokens") or 0)
        )
        out_tok = int(last_usage.get("output_tokens") or 0)
    return in_tok, out_tok, session_cost, last_model, priced_ok


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return f"{n/1_000_000:.1f}M"


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = str(data.get("session_id") or "unknown")
    transcript_path = data.get("transcript_path") or ""
    cwd = data.get("cwd") or os.getcwd()
    # Stop hook input does not include model; read it from the transcript below.
    model_from_input = data.get("model") or os.environ.get("CLAUDE_MODEL") or ""

    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%b %d")

    dir_name = Path(cwd).name or "?"
    branch = _safe(lambda: _git_branch(cwd), None)
    dir_branch = f"{dir_name}/{branch}" if branch else dir_name

    turn = _safe(lambda: _bump_turn_counter(session_id), 0)
    in_tok, out_tok, cost, model_from_transcript, priced_ok = _safe(
        lambda: _parse_transcript(transcript_path), (0, 0, 0.0, "", False)
    )

    model = model_from_transcript or model_from_input
    model_short = _short_model(model)
    tokens_part = f"{_fmt_tokens(in_tok)}↑/{_fmt_tokens(out_tok)}↓ tok"
    # An unpriced model makes the total an estimate — say so rather than quoting
    # a confident number produced by a fallback rate.
    cost_part = f"${cost:.2f} sess" if priced_ok else f"~${cost:.2f} sess (unpriced model)"

    # ANSI formatting: dim gray separator + bold cyan footer text. Matches the
    # CMEM SessionStart hook style which IS visibly rendered in the VSCode chat
    # panel — plain-text systemMessage from Stop hooks was being rendered too
    # subtly to notice (level: "suggestion").
    DIM = "\x1b[2m"
    BOLD = "\x1b[1m"
    CYAN = "\x1b[36m"
    GRAY = "\x1b[90m"
    RESET = "\x1b[0m"
    sep = f"{GRAY}{'─' * 76}{RESET}"
    body = f"{BOLD}{CYAN}{time_str} · {date_str} · {model_short}{RESET}{DIM} · {dir_branch} · turn {turn} · {tokens_part} · {cost_part}{RESET}"
    line = f"{sep}\n{body}"

    # Stop hooks emit JSON; systemMessage is shown in the transcript.
    print(json.dumps({"systemMessage": line}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never break the session
        sys.exit(0)
