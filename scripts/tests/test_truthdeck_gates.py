from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from truthdeck_gates import evaluate, overall_state  # noqa: E402
from truthdeck_model import FactState, GateState, ReasonCode, STAGE_ORDER, Stage, make_fact  # noqa: E402


NOW = "2026-07-22T12:00:00Z"


def fact(key, value, *, state=FactState.OBSERVED, fresh=None):
    return make_fact(key, value, state=state, source_type="test", source_locator="fixture",
                     observed_at_utc=NOW, fresh_until_utc=fresh, repo_id="repo")


class TruthDeckGateTests(unittest.TestCase):
    def test_happy_path_and_runtime_na(self) -> None:
        facts = [
            fact("plan.parseable", True), fact("plan.risk", "R1"), fact("plan.blocked", False),
            fact("implementation.head", "abc"), fact("review.head", "abc"),
            fact("review.blocking_findings", 0), fact("ci.head", "abc"), fact("ci.passed", True),
            fact("pr.merged", True), fact("runtime.applicable", False),
        ]
        gates, action = evaluate(facts)
        self.assertEqual(overall_state(gates, STAGE_ORDER), GateState.PASS)
        self.assertEqual(gates[-1].state, GateState.NOT_APPLICABLE)
        self.assertEqual(action.action_id, "ready_for_operator_review")

    def test_stale_review_cannot_pass(self) -> None:
        gates, action = evaluate([
            fact("implementation.head", "new"), fact("review.head", "old"), fact("review.blocking_findings", 0)
        ], required=(Stage.EXACT_HEAD_REVIEWED,))
        gate = next(x for x in gates if x.stage == Stage.EXACT_HEAD_REVIEWED)
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn(ReasonCode.REVIEW_STALE_HEAD, gate.reason_codes)
        self.assertEqual(action.stage, Stage.EXACT_HEAD_REVIEWED)

    def test_expired_runtime_fact_is_unknown(self) -> None:
        gates, _ = evaluate([
            fact("runtime.applicable", True), fact("runtime.ready", True, fresh="2026-07-22T11:59:59Z"),
            fact("runtime.sample_count", 1, fresh="2026-07-22T11:59:59Z"),
        ], required=(Stage.RUNTIME_PROVEN,), evaluated_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC))
        gate = next(x for x in gates if x.stage == Stage.RUNTIME_PROVEN)
        self.assertEqual(gate.state, GateState.UNKNOWN)
        self.assertIn(ReasonCode.EVIDENCE_STALE, gate.reason_codes)

    def test_boundary_precedes_other_actions(self) -> None:
        _, action = evaluate([], boundary_violation=True)
        self.assertEqual(action.reason_codes, (ReasonCode.BOUNDARY_REFUSAL,))

    def test_dirty_tree_is_not_exact_implementation(self) -> None:
        gates, _ = evaluate([fact("implementation.head", "abc"), fact("git.clean", False)], required=(Stage.IMPLEMENTED,))
        gate = next(x for x in gates if x.stage == Stage.IMPLEMENTED)
        self.assertEqual(gate.state, GateState.BLOCKED)
        self.assertIn(ReasonCode.DIRTY_OPERATOR_CHECKOUT, gate.reason_codes)

    def test_r2_cannot_self_authorize(self) -> None:
        gates, action = evaluate([
            fact("plan.parseable", True), fact("plan.risk", "R2"), fact("plan.blocked", False),
            fact("authorization.state", "ASSERTED_UNVERIFIED"),
        ], required=(Stage.PLANNED,))
        gate = next(x for x in gates if x.stage == Stage.PLANNED)
        self.assertEqual(gate.state, GateState.HOLD)
        self.assertIn(ReasonCode.AUTHORIZATION_UNKNOWN, gate.reason_codes)
        self.assertEqual(action.risk, "R2")
        self.assertIn("broker_or_order_path", action.forbidden_actions)


if __name__ == "__main__":
    unittest.main()
