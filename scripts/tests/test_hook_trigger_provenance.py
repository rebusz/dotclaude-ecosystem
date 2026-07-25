#!/usr/bin/env python3
"""Regression tests for the 2026-07-25 hook defects.

Two independent bugs, one test module because both are "the hook told the
operator something untrue":

  1. plan_keyword_detector matched trigger words inside PASTED material. A
     Reddit thread quoting "tracking structural drift over long sessions" fired
     the steering branch and injected 13.5 KB into an unrelated turn.
  2. answer_footer priced every Opus turn off a stale table (Opus 3/4.0 rates
     for the whole 4.x line, no Claude 5 entry at all), so the per-turn session
     cost shown to the operator was wrong on every model that matters.

Pure functions only: no FS, no subprocess, no network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import answer_footer as af  # noqa: E402  (sys.path must be set first)
import plan_keyword_detector as pkd  # noqa: E402


def _fires(prompt: str) -> tuple[bool, bool]:
    """(plan_match, steer_match) under the real matching path."""
    scannable = pkd.operator_text(prompt)
    return (
        any(rx.search(scannable) for rx in pkd.COMPILED),
        any(rx.search(scannable) for rx in pkd.STEER_COMPILED),
    )


# Trimmed but structurally faithful reproduction of the pasted thread: markdown
# links, usernames, and the trigger word buried in a third-party comment.
PASTED_THREAD = (
    "What's a Claude hidden gem feature or prompt technique?\n"
    "[Claude Code Workflow](https://www.reddit.com/r/ClaudeAI/)\n"
    + ("Some commenter said something unremarkable about their setup. " * 60)
    + "\nThat spec-driven architecture is smart for keeping token usage low. "
    "Having a dedicated document just for architectural changes is a lifesaver "
    "for tracking structural drift over long sessions.\n"
    + ("Another reply agreeing enthusiastically with the parent comment. " * 60)
    + "\n[deleted] Comment deleted by user\n"
)


class TestTriggerProvenance(unittest.TestCase):
    def test_operator_own_steer_phrase_still_fires(self):
        _, steer = _fires("co dalej z tym planem?")
        self.assertTrue(steer, "operator's own steering question must still fire")

    def test_operator_own_plan_phrase_still_fires(self):
        plan, _ = _fires("nowy plan na router sesji")
        self.assertTrue(plan, "operator's own plan phrase must still fire")

    def test_pasted_thread_does_not_fire(self):
        """The exact 2026-07-25 incident: 'drift' inside pasted third-party text."""
        self.assertIn("drift", PASTED_THREAD, "fixture must actually contain the trigger")
        plan, steer = _fires(PASTED_THREAD)
        self.assertFalse(steer, "a trigger inside pasted material must not fire steering")
        self.assertFalse(plan, "a trigger inside pasted material must not fire plan context")

    def test_blockquoted_trigger_does_not_fire(self):
        prompt = "Zobacz co pisze kolega:\n> we keep tracking drift across sessions\nco o tym myslisz?"
        _, steer = _fires(prompt)
        self.assertFalse(steer, "blockquoted trigger must not fire")

    def test_fenced_trigger_does_not_fire(self):
        prompt = "Wklejam log:\n```\nWARN drift detected in branch\n```\nnaprawisz?"
        _, steer = _fires(prompt)
        self.assertFalse(steer, "fenced trigger must not fire")

    def test_trigger_at_tail_of_long_prompt_fires(self):
        """Operators put the ask at the end of a paste — that must survive."""
        prompt = PASTED_THREAD + "\n\nOK, przeczytales. Co dalej robimy?"
        _, steer = _fires(prompt)
        self.assertTrue(steer, "an operator ask after a paste must still fire")

    def test_trigger_at_head_of_long_prompt_fires(self):
        prompt = "Co dalej? Kontekst ponizej.\n\n" + PASTED_THREAD
        _, steer = _fires(prompt)
        self.assertTrue(steer, "an operator ask before a paste must still fire")

    def test_url_only_prompt_does_not_fire(self):
        prompt = "https://example.com/what-next-drift-report"
        plan, steer = _fires(prompt)
        self.assertFalse(steer or plan, "a trigger inside a bare URL must not fire")

    def test_short_unrelated_prompt_costs_nothing(self):
        plan, steer = _fires("popraw literowke w README")
        self.assertFalse(plan or steer)


class TestPricingTable(unittest.TestCase):
    def test_current_models_are_priced(self):
        for model in (
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-fable-5",
            "claude-haiku-4-5",
        ):
            self.assertIn(model, af._PRICING, f"{model} must be priced explicitly")

    def test_opus_5_rates(self):
        inp, out, _, _ = af._PRICING["claude-opus-5"]
        self.assertEqual((inp, out), (5.0, 25.0))

    def test_opus_4x_is_not_priced_as_opus_3(self):
        """The stale table charged 15/75 for the whole Opus 4 line."""
        for model in ("claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"):
            inp, out, _, _ = af._PRICING[model]
            self.assertEqual((inp, out), (5.0, 25.0), f"{model} mispriced")

    def test_cache_multipliers_hold(self):
        """cache write = 1.25x input, cache read = 0.10x input, on every row."""
        for model, (inp, _out, cc, cr) in af._PRICING.items():
            self.assertAlmostEqual(cc, inp * 1.25, places=4, msg=f"{model} cache write")
            self.assertAlmostEqual(cr, inp * 0.10, places=4, msg=f"{model} cache read")

    def test_opus_5_turn_cost(self):
        # 1M input + 1M output at Opus 5 rates.
        cost = af._calc_turn_cost("claude-opus-5", 1_000_000, 1_000_000, 0, 0)
        self.assertAlmostEqual(cost, 30.0, places=6)

    def test_unknown_model_does_not_fall_back_to_a_cheap_rate(self):
        """The old default silently used Sonnet rates, understating real spend."""
        known = af._calc_turn_cost("claude-opus-5", 1_000_000, 0, 0, 0)
        unknown = af._calc_turn_cost("claude-neverheardofit-9", 1_000_000, 0, 0, 0)
        self.assertGreaterEqual(unknown, known)

    def test_short_model_labels(self):
        self.assertEqual(af._short_model("claude-opus-5"), "OPUS-5")
        self.assertEqual(af._short_model("claude-sonnet-5"), "SONNET-5")
        self.assertEqual(af._short_model("claude-fable-5"), "FABLE-5")
        self.assertEqual(af._short_model("claude-opus-4-8"), "OPUS-4.8")
        self.assertEqual(af._short_model("claude-haiku-4-5"), "HAIKU-4.5")
        self.assertEqual(af._short_model(""), "?")


if __name__ == "__main__":
    unittest.main()
