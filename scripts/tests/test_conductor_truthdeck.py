"""Unit tests for ConductorTruthDeckSeam and Decision D4 exit code 12 handling."""

import json
import pathlib
import subprocess
from unittest.mock import patch, MagicMock

from scripts.conductor_truthdeck import ConductorTruthDeckSeam, check_truthctl_version
from scripts.conductor_workflow import ConductorWorkflowBridge
from scripts.conductor_model import WorkItem


def test_truthdeck_seam_exit_code_12(tmp_path: pathlib.Path):
    """Test Decision D4: exit code 12 with parseable JSON is a VALID snapshot with non-green gates."""
    manager = MagicMock()
    seam = ConductorTruthDeckSeam(repo_root=tmp_path, resource_manager=manager)

    output = json.dumps({
        "overall_status": "HOLD",
        "gates": {"clean_worktree": "PASS", "ci_status": "HOLD"}
    })

    manager.run_bounded_command.return_value = dict(exit_code=12, stdout=output, status="FAILED", quiescent=True)
    status, data = seam.run_checkpoint_snapshot(boundary="pre_dispatch", plan_path="design/plans/test.md")
    assert status == "HOLD"
    assert data["overall_status"] == "HOLD"
    call = manager.run_bounded_command.call_args
    assert call.kwargs["timeout_seconds"] == 120
    assert "--no-store" in call.args[0]


def test_truthdeck_timeout_cannot_turn_partial_json_into_green(tmp_path):
    manager = MagicMock()
    manager.run_bounded_command.return_value = dict(exit_code=0, stdout='{"overall_status":"PASS"}',
                                                    status="TIMEOUT", quiescent=True, lane_id="timed-out")
    seam = ConductorTruthDeckSeam(tmp_path, resource_manager=manager)
    status, data = seam.run_checkpoint_snapshot("pre_dispatch")
    assert status == "UNKNOWN" and data["error"] == "TIMEOUT"


def test_workflow_bridge_formatting():
    item = WorkItem(
        work_item_id="wi_wf_1",
        idempotency_key="key_wf_1",
        title="Workflow Task",
        repo_id="dotclaude-ecosystem",
        repo_path="D:/dotclaude/dotclaude-ecosystem",
        plan_path="design/plans/test.md",
        risk_class="R2",
        workflow="fwf",
        requested_terminal_stage="merged",
        job_kind="engineering_plan_lifecycle",
    )

    cmd = ConductorWorkflowBridge.get_workflow_command(item)
    assert cmd == "/fwf D:/dotclaude/dotclaude-ecosystem/design/plans/test.md"
    assert ConductorWorkflowBridge.validate_workflow_contract(item)


def test_truthctl_version_check_fails_closed_on_unknown_and_accepts_pinned_minimum():
    unknown = MagicMock(returncode=0, stdout="truthctl dev-build", stderr="")
    with patch("scripts.conductor_truthdeck.shutil.which", return_value="truthctl"), patch(
        "scripts.conductor_truthdeck.subprocess.run", return_value=unknown
    ):
        result = check_truthctl_version()
    assert result["ok"] is False
    assert result["status"] == "UNKNOWN"

    accepted = MagicMock(returncode=0, stdout="1.0.0\n", stderr="")
    with patch("scripts.conductor_truthdeck.shutil.which", return_value="truthctl"), patch(
        "scripts.conductor_truthdeck.subprocess.run", return_value=accepted
    ):
        result = check_truthctl_version()
    assert result["ok"] is True
    assert result["status"] == "PASS"

    with patch("scripts.conductor_truthdeck.shutil.which", return_value="truthctl"), patch(
        "scripts.conductor_truthdeck.subprocess.run",
        side_effect=subprocess.TimeoutExpired("truthctl", 10),
    ):
        result = check_truthctl_version()
    assert result["ok"] is False
    assert result["status"] == "UNKNOWN"
