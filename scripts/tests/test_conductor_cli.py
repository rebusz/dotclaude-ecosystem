"""Unit tests for conductorctl CLI, conductord coordinator, and conductor_mcp server."""

import json
import pathlib
import pytest

from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_mcp import handle_mcp_tool_call
from scripts.conductor_model import CommandEnvelope
from scripts.conductor_store import ConductorStore
from scripts.conductord import run_coordinator_loop


def test_mcp_tool_calls(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))

    store = ConductorStore(root_dir=tmp_path)
    processor = ConductorCommandProcessor(store=store)

    # Enqueue a WorkItem via processor
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_mcp_test",
            command_type="enqueue",
            payload={
                "idempotency_key": "idemp_mcp_task",
                "title": "MCP Task",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/test.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
            },
            idempotency_key="idemp_mcp_test",
        )
    )

    # Call conductor_status tool
    status_res = handle_mcp_tool_call("conductor_status", {})
    assert "total_work_items" in status_res
    assert status_res["total_work_items"] == 1


def test_coordinator_single_pass_loop(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))

    store = ConductorStore(root_dir=tmp_path)

    # Put a command envelope into inbox
    cmd = CommandEnvelope(
        command_id="cmd_inbox_loop",
        command_type="enqueue",
        payload={
            "idempotency_key": "idemp_inbox_loop",
            "title": "Inbox Loop Task",
            "repo_id": "dotclaude-ecosystem",
            "repo_path": "D:/dotclaude/dotclaude-ecosystem",
            "plan_path": "design/plans/test.md",
            "risk_class": "R1",
            "workflow": "fwf",
            "requested_terminal_stage": "merged",
            "job_kind": "engineering_plan_lifecycle",
        },
        idempotency_key="idemp_inbox_loop",
    )
    inbox_file = store.put_inbox_envelope(cmd)
    assert inbox_file.exists()

    # Run single pass coordinator loop
    run_coordinator_loop(poll_interval_seconds=0.1, single_pass=True)

    # Verify inbox file was processed and removed
    assert not inbox_file.exists()

    # Verify receipt exists
    receipt = store.get_receipt("idemp_inbox_loop")
    assert receipt is not None
    assert receipt.status == "SUCCESS"


def test_resource_recover_cli_round_trip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """Drive the real conductorctl surface, refusal branch included."""
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))

    from datetime import datetime, timedelta, timezone

    from scripts import conductorctl
    from scripts.conductor_resources import DEFAULT_LEASE_TTL_SECONDS, HostResourceManager

    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)
    wedged = manager.request(purpose="cdp_provider", attempt_id="at-cli", agent_instance="inst-cli")
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))
    queued = manager.request(purpose="pytest_full", attempt_id="at-cli-queued", agent_instance="inst-cli")

    # Without attestation the CLI must fail closed and exit non-zero.
    assert conductorctl.main(["resource-recover", "--request-id", wedged["request_id"]]) == 1
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["status"] == "ERROR"
    assert "OWNER_LIVENESS_UNPROVEN" in refusal["error_message"]

    exit_code = conductorctl.main(
        [
            "resource-recover",
            "--request-id",
            wedged["request_id"],
            "--attest-owner-gone",
            "--reason",
            "owning agent host is gone",
        ]
    )
    assert exit_code == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "SUCCESS"
    assert receipt["result"]["evidence"] == "OPERATOR_ATTESTED"
    assert receipt["result"]["promoted"]["request_id"] == queued["request_id"]

    status = HostResourceManager(ConductorStore(root_dir=tmp_path)).status()
    assert status["recovery_required"] == 0
    assert status["active_units"] == 1
