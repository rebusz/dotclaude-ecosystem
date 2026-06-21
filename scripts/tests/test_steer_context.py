#!/usr/bin/env python3
"""Tests for steer_context.py — the heuristic (coverage/drift) is the risky part,
so it gets the coverage. Pure functions only: no FS, no git, no subprocess."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import steer_context as sc


# A realistic, slightly messy DoD slice (mirrors the tsu-execution-authority vision).
SAMPLE_VISION = """\
# TSU

## North Star
**The goal is live-trading income — not a hobby.** Shortest sound path to funded $$$.

## Definition of Done
- **Custody is never lost.** kill-9 / restart always reconciles to broker truth.
- **No silent global blocks.** Every halt is race-aware and evidence-grounded.
- **All horizon lanes always-on.** micro_scalp / intraday / swing / LEAPS produce SignalCards.
- plain bullet without bold — must be ignored by aspect extraction
- **Replayable by construction.** Identical semantics live and in LAB replay.

## Roadmap
### P1 — Broker spine — CLOSED
"""


class TestExtractSection(unittest.TestCase):
    def test_reads_until_next_h2(self):
        ns = sc._extract_section(SAMPLE_VISION, "## North Star")
        self.assertIn("live-trading income", ns)
        self.assertNotIn("Definition of Done", ns)
        self.assertNotIn("Custody", ns)

    def test_missing_section_is_empty(self):
        self.assertEqual(sc._extract_section(SAMPLE_VISION, "## Nope"), "")


class TestDeriveKeywords(unittest.TestCase):
    def test_drops_stopwords_and_short_tokens(self):
        kws = sc._derive_keywords("Custody is never lost")
        self.assertIn("custody", kws)
        self.assertNotIn("is", kws)      # stopword
        self.assertNotIn("never", kws)   # stopword
        # "lost" is 4 chars, content -> kept
        self.assertIn("lost", kws)

    def test_hyphenated_kept(self):
        kws = sc._derive_keywords("All horizon lanes always-on")
        self.assertIn("horizon", kws)
        self.assertIn("lanes", kws)
        self.assertIn("always-on", kws)


class TestDodAspects(unittest.TestCase):
    def test_only_bold_bullets_become_aspects(self):
        aspects = sc._dod_aspects(SAMPLE_VISION)
        titles = [t for t, _ in aspects]
        self.assertIn("Custody is never lost", titles)
        self.assertIn("No silent global blocks", titles)
        self.assertIn("Replayable by construction", titles)
        self.assertEqual(len(titles), 4)  # the plain bullet is excluded
        # each aspect carries non-empty derived keywords
        self.assertTrue(all(kw for _, kw in aspects))


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.aspects = sc._dod_aspects(SAMPLE_VISION)

    def test_matched_aspect_is_active_with_evidence(self):
        corpus = ["fix(custody): reconcile stop on reconnect", "docs: tidy readme"]
        rows = {r["aspect"]: r for r in sc._coverage(self.aspects, corpus)}
        self.assertTrue(rows["Custody is never lost"]["active"])
        self.assertIn("custody", rows["Custody is never lost"]["evidence"])

    def test_unmatched_aspect_is_candidate_gap(self):
        corpus = ["fix(custody): reconcile stop"]
        rows = {r["aspect"]: r for r in sc._coverage(self.aspects, corpus)}
        # nothing in the corpus mentions replay/horizon/halt -> flagged inactive
        self.assertFalse(rows["Replayable by construction"]["active"])
        self.assertEqual(rows["Replayable by construction"]["evidence"], "")

    def test_empty_corpus_flags_everything(self):
        rows = sc._coverage(self.aspects, [])
        self.assertTrue(all(not r["active"] for r in rows))

    def test_match_is_case_insensitive(self):
        rows = {r["aspect"]: r for r in sc._coverage(self.aspects, ["REPLAYABLE harness landed"])}
        self.assertTrue(rows["Replayable by construction"]["active"])


if __name__ == "__main__":
    unittest.main()
