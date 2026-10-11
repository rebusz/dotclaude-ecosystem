"""Behavior checks for the ordered pytest evidence contract."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest_order_evidence as evidence  # noqa: E402


FIRST = "tests/feed/test_gex_feed.py::test_connection_error_never_invokes_reauth"
SECOND = "tests/feed/test_gex_feed.py::test_replay_2026_09_21_empty_200_does_not_loop_logins"
SEED = 1745556883
HEAD = "eb4ca3c54a1d9fe9801839b1ce996d3e3f6e1edc"


def receipt() -> dict[str, object]:
    return {
        "source_head": HEAD,
        "command": [
            "python", "-m", "pytest", "-q", "-vv", "--randomly-dont-reorganize",
            f"--randomly-seed={SEED}", FIRST, SECOND,
        ],
        "requested_order": [FIRST, SECOND],
        "requested_seed": SEED,
        "observed_seed": SEED,
        "observed_order_and_results": [[FIRST, "PASSED"], [SECOND, "PASSED"]],
        "native_exit": 0,
        "outer_timeout": False,
    }


def stdout(first: str = FIRST, second: str = SECOND, seed: int = SEED) -> str:
    return (
        "================ test session starts ================\n"
        f"Using --randomly-seed={seed}\ncollected 2 items\n\n"
        f"{first} PASSED [ 50%]\n{second} PASSED [100%]\n"
        "================ 2 passed in 1.00s ================\n"
    )


class TestOrderedPytestEvidence(unittest.TestCase):
    def test_exact_requested_and_observed_pair_is_proven(self):
        result = evidence.assess(receipt(), stdout())
        self.assertEqual(result["verdict"], "ORDERED_PAIR_PROVEN")
        self.assertEqual(result["native_state"], "PASS")

    def test_reversed_execution_cannot_be_claimed_as_ordered(self):
        run = receipt()
        run["observed_order_and_results"] = [[SECOND, "PASSED"], [FIRST, "PASSED"]]
        result = evidence.assess(run, stdout(SECOND, FIRST))
        self.assertEqual(result["verdict"], "ORDER_NOT_PROVEN")
        self.assertIn("observed_order_differs_from_requested", result["mismatches"])
        self.assertEqual(result["native_state"], "PASS")

    def test_quiet_failed_run_keeps_order_and_seed_unknown(self):
        result = evidence.assess({"native_exit": 1, "outer_timeout": False}, "...F...F...")
        self.assertEqual(result["verdict"], "ORDER_NOT_PROVEN")
        self.assertEqual(result["order_state"], "UNKNOWN")
        self.assertEqual(result["native_state"], "FAILED")
        self.assertIn("stdout_seed", result["unknown_fields"])

    def test_outer_success_cannot_hide_child_failure_or_timeout(self):
        failed = receipt()
        failed["native_exit"] = 1
        self.assertEqual(evidence.assess(failed, stdout())["native_state"], "FAILED")
        timed_out = receipt()
        timed_out["outer_timeout"] = True
        self.assertEqual(evidence.assess(timed_out, stdout())["native_state"], "TIMEOUT")
        self.assertEqual(evidence.assess(timed_out, stdout())["verdict"], "ORDER_NOT_PROVEN")

    def test_missing_seed_or_reorganization_guard_is_not_proven(self):
        run = receipt()
        run["command"].remove("--randomly-dont-reorganize")
        result = evidence.assess(run, stdout(seed=SEED + 1))
        self.assertEqual(result["verdict"], "ORDER_NOT_PROVEN")
        self.assertIn("reorganization_not_disabled", result["mismatches"])
        self.assertIn("seed_differs_from_requested", result["mismatches"])

    def test_second_session_header_cannot_borrow_first_seed_and_count(self):
        second_header = (
            "================ test session starts ================\n"
            "Using --randomly-seed=42\ncollected 2 items\n"
        )
        mixed_log = stdout().replace(f"{FIRST} PASSED", second_header + f"{FIRST} PASSED")
        result = evidence.assess(receipt(), mixed_log)
        self.assertEqual(result["verdict"], "ORDER_NOT_PROVEN")
        self.assertIn("multiple_session_headers", result["mismatches"])
        self.assertIn("multiple_stdout_seeds", result["mismatches"])
        self.assertIn("multiple_collection_headers", result["mismatches"])

    def test_results_before_session_header_cannot_be_proven(self):
        header = (
            "================ test session starts ================\n"
            f"Using --randomly-seed={SEED}\ncollected 2 items\n"
            "================ 2 passed in 1.00s ================\n"
        )
        results = f"{FIRST} PASSED [ 50%]\n{SECOND} PASSED [100%]\n"
        result = evidence.assess(receipt(), results + header)
        self.assertEqual(result["verdict"], "ORDER_NOT_PROVEN")
        self.assertIn("results_outside_session_order", result["mismatches"])

    def test_cli_emits_unicode_node_safely_on_cp1252_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unicode_node = FIRST + "[雪]"
            run = receipt()
            run["command"][-2] = unicode_node
            run["requested_order"][0] = unicode_node
            run["observed_order_and_results"][0][0] = unicode_node
            log = root / "pytest.stdout.log"
            log.write_text(stdout(first=unicode_node), encoding="utf-8")
            run["stdout"] = str(log)
            record = root / "receipt.json"
            record.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
            output = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
            with mock.patch("sys.stdout", output):
                code = evidence.main(["--receipt", str(record)])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
