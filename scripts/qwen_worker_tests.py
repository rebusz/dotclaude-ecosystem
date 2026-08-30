"""The one entry point a local LLM worker uses to run tests.

Every run is admitted through the capacity-one ``host:heavy`` gate rather than
launching pytest freely. See ``gate_focused_runs`` for the one policy choice
this module makes on top of the Conductor's own classification.
"""

import re

from scripts.conductor_resources import HostResourceManager

_TARGET_PATTERN = re.compile(r"^tests?/[A-Za-z0-9_./\\-]+\.py(::[A-Za-z0-9_]+)?$")

_RETRY_AFTER_S = 20
_OUTPUT_TAIL_LINES = 40
_OUTPUT_TAIL_CHARS = 4000


def run_worker_tests(*, repo_dir, python_executable, target, attempt_id,
                     agent_instance, store, gate_focused_runs: bool = True) -> dict:
    """Run one test target for the worker, through host admission.

    ``gate_focused_runs`` defaults to True and is the deliberate departure from
    the Conductor's own policy. The Conductor classifies a single-file target as
    ``pytest_focused`` and lets it run WITHOUT taking the heavy lease, because a
    focused run by a trusted caller is cheap and should not serialize. This
    caller is not trusted: it is a local model that can pick any target, on a
    workstation that also runs the live trading stack. Serializing its runs is
    the point of routing them here at all. Pass False only for a caller that has
    its own containment.
    """
    if not _TARGET_PATTERN.match(target):
        return {
            "status": "DENIED",
            "error_code": "INVALID_TEST_TARGET",
            "message": f"rejected test target: {target!r}",
            "allowed_syntax": "tests/test_x.py or tests/test_x.py::test_case",
        }

    result = HostResourceManager(store).run_bounded_pytest(
        python_executable=python_executable,
        pytest_args=[target],
        cwd=repo_dir,
        attempt_id=attempt_id,
        agent_instance=agent_instance,
        force_heavy=gate_focused_runs,
    )

    if result.get("status") == "QUEUED":
        return {
            "status": "LEASE_BUSY",
            "retry_after_s": _RETRY_AFTER_S,
            "reason_code": result.get("reason_code"),
        }

    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""

    summary = ""
    for line in reversed(stdout.splitlines()):
        if line.strip():
            summary = line
            break

    combined_lines = (stdout + "\n" + stderr).splitlines()
    output_tail = "\n".join(combined_lines[-_OUTPUT_TAIL_LINES:])
    output_tail = output_tail[-_OUTPUT_TAIL_CHARS:]

    return {
        "status": result.get("status"),
        "exit_code": result.get("exit_code"),
        "summary": summary,
        "output_tail": output_tail,
    }
