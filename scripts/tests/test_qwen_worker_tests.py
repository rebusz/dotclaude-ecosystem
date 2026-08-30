import sys

from scripts.conductor_resources import HostResourceManager
from scripts.conductor_store import ConductorStore
from scripts.qwen_worker_tests import run_worker_tests


def test_flag_carrying_target_is_denied(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    result = run_worker_tests(
        repo_dir=tmp_path,
        python_executable=sys.executable,
        target="-s tests/test_x.py",
        attempt_id="attempt-1",
        agent_instance="qwen-worker",
        store=store,
    )
    assert result["status"] == "DENIED"
    assert result["error_code"] == "INVALID_TEST_TARGET"
    assert "'-s tests/test_x.py'" in result["message"]
    assert result["allowed_syntax"] == "tests/test_x.py or tests/test_x.py::test_case"


def test_busy_lease_returns_lease_busy_without_running_pytest(tmp_path):
    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)
    manager.request(purpose="pytest_full", attempt_id="holder", agent_instance="holder")

    result = run_worker_tests(
        repo_dir=tmp_path,
        python_executable=sys.executable,
        target="tests/test_x.py",
        attempt_id="attempt-2",
        agent_instance="qwen-worker",
        store=store,
    )

    assert result["status"] == "LEASE_BUSY"
    assert result["reason_code"] == "HOST_RESOURCE_BUSY"
    assert result["retry_after_s"] == 20
    assert "exit_code" not in result
    assert "output_tail" not in result


def test_real_passing_run(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    store = ConductorStore(root_dir=tmp_path)

    result = run_worker_tests(
        repo_dir=tmp_path,
        python_executable=sys.executable,
        target="tests/test_ok.py",
        attempt_id="attempt-3",
        agent_instance="qwen-worker",
        store=store,
    )

    assert result["status"] == "PASSED"
    assert result["exit_code"] == 0


def test_focused_run_is_gated_by_default_and_ungated_when_asked(tmp_path):
    """The one policy choice this module makes on top of the Conductor.

    A single-file target is `pytest_focused`, which the Conductor deliberately
    lets run without the heavy lease. The worker lane overrides that, so pin
    both halves: gated by default, ungated only on explicit request.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    store = ConductorStore(root_dir=tmp_path)
    HostResourceManager(store).request(
        purpose="pytest_full", attempt_id="holder", agent_instance="holder"
    )

    gated = run_worker_tests(
        repo_dir=tmp_path, python_executable=sys.executable,
        target="tests/test_ok.py", attempt_id="attempt-gated",
        agent_instance="qwen-worker", store=store,
    )
    assert gated["status"] == "LEASE_BUSY"

    ungated = run_worker_tests(
        repo_dir=tmp_path, python_executable=sys.executable,
        target="tests/test_ok.py", attempt_id="attempt-ungated",
        agent_instance="qwen-worker", store=store, gate_focused_runs=False,
    )
    assert ungated["status"] == "PASSED"
    assert ungated["exit_code"] == 0
