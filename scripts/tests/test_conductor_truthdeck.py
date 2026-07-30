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
    seam = ConductorTruthDeckSeam(repo_root=tmp_path)

    mock_res = MagicMock()
    mock_res.returncode = 12
    mock_res.stdout = json.dumps({
        "overall_status": "HOLD",
        "gates": {"clean_worktree": "PASS", "ci_status": "HOLD"}
    })

    with patch("subprocess.run", return_value=mock_res):
        status, data = seam.run_checkpoint_snapshot(boundary="pre_dispatch", plan_path="design/plans/test.md")
        assert status == "HOLD"
        assert data["overall_status"] == "HOLD"


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
