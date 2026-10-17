#!/usr/bin/env python3
"""Neutralize repository-derived text before it is injected into an agent turn.

The context hooks (plan_context_loader, steer_context) quote repository files --
vision docs, IDEA_BOX, PLANS.md, commit subjects, plan slugs -- inside tagged
blocks like ``<plan-context>`` that the agent reads as trusted context. Any
contributor can write those files, so quoted text must not be able to close the
block, open a new tag that looks like harness output (``<system-reminder>``),
or smuggle control characters (audit security F2/F11).

Two shapes:

* ``clean_fact`` -- one line: whitespace collapsed, every angle bracket
  replaced, truncated. For attribute values, slugs, commit subjects, notes.
* ``neutralize`` -- a block: newlines kept, only a ``<`` that could start a tag
  (``<x``, ``</``, ``<!``, ``<?``) replaced, so prose like ``a -> b`` or
  ``x <= 3`` reads unchanged. For quoted markdown sections.

Neither decides what is trustworthy; the injecting hook states that boundary.
"""
from __future__ import annotations

import re

# C0 controls except TAB/LF/CR, plus DEL. NUL and ESC are the ones that matter:
# NUL truncates some consumers, ESC drives terminal escape sequences.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAG_START = re.compile(r"<(?=[A-Za-z/!?])")


def clean_fact(value: object, limit: int = 140) -> str:
    text = " ".join(_CONTROL.sub("", str(value)).split())
    text = text.replace("<", "‹").replace(">", "›").replace('"', "'")
    return text[:limit]


def neutralize(text: str, limit: int | None = None) -> str:
    text = _TAG_START.sub("‹", _CONTROL.sub("", text))
    if limit is not None and len(text) > limit:
        text = text[:limit] + "… _(truncated)_"
    return text
