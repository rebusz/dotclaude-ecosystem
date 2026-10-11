#!/usr/bin/env python3
"""Read-only check of an ordered two-node pytest receipt and its retained -vv log."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


RESULT = re.compile(r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.M)
SESSION = re.compile(r"^=+ test session starts =+$", re.M)
SEED = re.compile(r"Using --randomly-seed=(\d+)")
COLLECTED = re.compile(r"\bcollected (\d+) items?\b")
SUMMARY = re.compile(r"^=+\s+(\d+) passed\b.*=+$", re.M)


def assess(receipt: dict[str, Any], stdout: str) -> dict[str, Any]:
    """Require both observed order and native success; never infer missing evidence."""
    unknown: list[str] = []
    mismatches: list[str] = []

    requested = receipt.get("requested_order")
    if not (
        isinstance(requested, list)
        and len(requested) == 2
        and all(isinstance(node, str) and "::" in node for node in requested)
        and requested[0] != requested[1]
    ):
        unknown.append("requested_order")
        requested = None

    command = receipt.get("command")
    if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
        unknown.append("command")
        command = None

    requested_seed = receipt.get("requested_seed")
    if type(requested_seed) is not int:
        unknown.append("requested_seed")
        requested_seed = None

    result_lines = list(RESULT.finditer(stdout))
    observed = [match.groups() for match in result_lines]
    recorded_observed = receipt.get("observed_order_and_results")
    if not isinstance(recorded_observed, list):
        unknown.append("recorded_observed_order")
    elif [list(pair) for pair in observed] != recorded_observed:
        mismatches.append("receipt_observed_order_differs_from_stdout")

    sessions = list(SESSION.finditer(stdout))
    if not sessions:
        unknown.append("session_header")
    elif len(sessions) != 1:
        mismatches.append("multiple_session_headers")

    seed_headers = list(SEED.finditer(stdout))
    observed_seed = int(seed_headers[0].group(1)) if len(seed_headers) == 1 else None
    if not seed_headers:
        unknown.append("stdout_seed")
    elif len(seed_headers) != 1:
        mismatches.append("multiple_stdout_seeds")
    recorded_seed = receipt.get("observed_seed")
    if type(recorded_seed) is not int:
        unknown.append("recorded_observed_seed")
    elif observed_seed is not None and recorded_seed != observed_seed:
        mismatches.append("receipt_seed_differs_from_stdout")

    collection_headers = list(COLLECTED.finditer(stdout))
    collected = int(collection_headers[0].group(1)) if len(collection_headers) == 1 else None
    if not collection_headers:
        unknown.append("collected_count")
    elif len(collection_headers) != 1:
        mismatches.append("multiple_collection_headers")
    elif collected != 2:
        mismatches.append("collected_count_not_two")

    summaries = list(SUMMARY.finditer(stdout))
    if not summaries:
        unknown.append("completion_summary")
    elif len(summaries) != 1 or int(summaries[0].group(1)) != 2:
        mismatches.append("completion_summary_not_two_passed")

    if (len(sessions) == len(seed_headers) == len(collection_headers)
            == len(summaries) == 1 and result_lines):
        positions = [sessions[0].start(), seed_headers[0].start(),
                     collection_headers[0].start(),
                     *(line.start() for line in result_lines), summaries[0].start()]
        if positions != sorted(set(positions)):
            mismatches.append("results_outside_session_order")

    if not observed:
        unknown.append("stdout_node_results")
    elif requested is not None and [node for node, _ in observed] != requested:
        mismatches.append("observed_order_differs_from_requested")
    if observed and any(status != "PASSED" for _, status in observed):
        mismatches.append("node_result_not_passed")
    if requested_seed is not None and observed_seed is not None and requested_seed != observed_seed:
        mismatches.append("seed_differs_from_requested")

    if command is not None:
        if command[1:3] != ["-m", "pytest"] or "-vv" not in command:
            mismatches.append("not_verbose_python_pytest")
        if "--randomly-dont-reorganize" not in command:
            mismatches.append("reorganization_not_disabled")
        if requested_seed is not None and f"--randomly-seed={requested_seed}" not in command:
            mismatches.append("requested_seed_not_in_argv")
        if requested is not None and [arg for arg in command if "::" in arg] != requested:
            mismatches.append("argv_targets_differ_from_requested")

    head = receipt.get("source_head")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        unknown.append("source_head")

    native_exit = receipt.get("native_exit")
    timed_out = receipt.get("outer_timeout")
    if type(native_exit) is not int:
        unknown.append("native_exit")
    if type(timed_out) is not bool:
        unknown.append("outer_timeout")
    native_state = (
        "UNKNOWN" if type(native_exit) is not int or type(timed_out) is not bool
        else "TIMEOUT" if timed_out
        else "PASS" if native_exit == 0
        else "FAILED"
    )
    order_state = "UNKNOWN" if unknown else "MISMATCH" if mismatches else "MATCH"
    proven = order_state == "MATCH" and native_state == "PASS"

    return {
        "verdict": "ORDERED_PAIR_PROVEN" if proven else "ORDER_NOT_PROVEN",
        "order_state": order_state,
        "native_state": native_state,
        "requested_order": requested,
        "observed_order_and_results": [list(pair) for pair in observed],
        "requested_seed": requested_seed,
        "observed_seed": observed_seed,
        "collected_count": collected,
        "native_exit": native_exit,
        "outer_timeout": timed_out,
        "unknown_fields": unknown,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise ValueError("receipt must be a JSON object")
        stdout_path = Path(receipt["stdout"])
        if not stdout_path.is_absolute():
            stdout_path = args.receipt.parent / stdout_path
        stdout = stdout_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"verdict": "ORDER_NOT_PROVEN", "error": str(exc)}))
        return 2
    result = assess(receipt, stdout)
    print(json.dumps(result))
    return 0 if result["verdict"] == "ORDERED_PAIR_PROVEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
