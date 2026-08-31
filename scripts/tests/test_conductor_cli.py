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

    from scripts.conductor_model import HostResourceRequestState
    from scripts.conductor_resources import current_utc_iso
    with store._connection() as conn:
        conn.execute(
            """
            INSERT INTO host_resource_requests (
                request_id, idempotency_key, resource_key, purpose, attempt_id,
                agent_instance, state, priority, command_sha256, created_at_utc,
                reason_code, slot_key, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rr_123456abcdef",
                "idemp_cli_wedged",
                "host:heavy",
                "pytest_heavy",
                "at-cli",
                "inst-cli",
                HostResourceRequestState.RECOVERY_REQUIRED.value,
                50,
                "",
                current_utc_iso(),
                "LEASE_EXPIRED",
                "",
                "conductor.resource-request.v1",
            ),
        )
    queued = manager.request(purpose="pytest_full", attempt_id="at-cli-queued", agent_instance="inst-cli")

    # Without attestation the CLI must fail closed and exit non-zero.
    assert conductorctl.main(["resource-recover", "--request-id", "rr_123456abcdef"]) == 1
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["status"] == "ERROR"
    assert "OWNER_LIVENESS_UNPROVEN" in refusal["error_message"]

    exit_code = conductorctl.main(
        [
            "resource-recover",
            "--request-id",
            "rr_123456abcdef",
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


def test_conductor_doctor_gate_clear_and_occupied(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    from scripts import conductorctl
    from scripts.conductor_resources import HostResourceManager

    store = ConductorStore(root_dir=tmp_path)
    # Clear gate: doctor must report PASS
    code = conductorctl.main(["doctor", "--json"])
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["doctor_status"] == "PASS"
    assert doc["resource"]["active_units"] == 0
    assert doc["resource"]["pool_exists"] is True

    # Merely occupied gate (ACTIVE request): doctor must still report PASS (occupied is healthy)
    manager = HostResourceManager(store)
    manager.request(purpose="pytest_full", attempt_id="at-doc-1", agent_instance="inst-doc")
    code = conductorctl.main(["doctor", "--json"])
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["doctor_status"] == "PASS"
    assert doc["resource"]["active_units"] == 1
    assert doc["resource"]["recovery_required"] == 0


def test_conductor_doctor_fails_when_recovery_required(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    from datetime import datetime, timedelta, timezone
    from scripts import conductorctl
    from scripts.conductor_resources import DEFAULT_LEASE_TTL_SECONDS, HostResourceManager

    store = ConductorStore(root_dir=tmp_path)
    manager = HostResourceManager(store)
    manager.request(purpose="pytest_full", attempt_id="at-doc-rec", agent_instance="inst-doc")
    manager.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS + 60))

    code = conductorctl.main(["doctor", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["doctor_status"] == "BLOCKED"
    assert doc["resource"]["recovery_required"] >= 1
    # The whole point: a wedged gate must fail closed for a script that only
    # checks the exit code, not just print BLOCKED into JSON nobody parses.
    assert code == 1


def test_conductor_doctor_absent_store_reports_absent_and_exits_zero(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    """An uninitialised host is a fact to report, not a failure to raise."""
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path / "never-created"))
    from scripts import conductorctl

    code = conductorctl.main(["doctor", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["store_state"] == "ABSENT"
    assert doc["doctor_status"] == "ABSENT"
    assert code == 0
    assert not (tmp_path / "never-created").exists()


def test_conductor_doctor_fails_when_pool_disabled(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    from scripts import conductorctl

    store = ConductorStore(root_dir=tmp_path)
    with store._connection() as conn:
        conn.execute("UPDATE host_resource_pools SET enabled = 0 WHERE resource_key = 'host:heavy'")

    code = conductorctl.main(["doctor", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["doctor_status"] == "BLOCKED"
    assert doc["resource"]["enabled"] is False
    assert code == 1


def test_conductor_doctor_fails_when_pool_row_absent(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    from scripts import conductorctl

    store = ConductorStore(root_dir=tmp_path)
    with store._connection() as conn:
        conn.execute("DELETE FROM host_resource_pools WHERE resource_key = 'host:heavy'")

    code = conductorctl.main(["doctor", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["doctor_status"] == "BLOCKED"
    assert doc["resource"]["pool_exists"] is False
    assert code == 1


def test_conductorctl_resource_request_routing_and_slot_key(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    monkeypatch.setenv("TDCONDUCTOR_DIR", str(tmp_path))
    from scripts import conductorctl

    # 1. Request via --purpose cdp_perplexity and --slot-key kimi-3
    code1 = conductorctl.main(
        [
            "resource-request",
            "--purpose",
            "cdp_perplexity",
            "--attempt-id",
            "at-cli-1",
            "--agent-instance",
            "ag-cli-1",
            "--slot-key",
            "kimi-3",
            "--priority",
            "80",
        ]
    )
    assert code1 == 0
    out1 = json.loads(capsys.readouterr().out)
    assert out1["status"] == "SUCCESS"
    assert out1["result"]["resource_key"] == "cdp:perplexity"
    assert out1["result"]["slot_key"] == "kimi-3"
    assert out1["result"]["priority"] == 80

    # 2. Request via --role chatgpt
    code2 = conductorctl.main(
        [
            "resource-request",
            "--purpose",
            "cdp_chatgpt",
            "--role",
            "chatgpt",
            "--attempt-id",
            "at-cli-2",
            "--agent-instance",
            "ag-cli-2",
        ]
    )
    assert code2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["status"] == "SUCCESS"
    assert out2["result"]["resource_key"] == "cdp:chatgpt"

    # 3. resource-live --all
    code3 = conductorctl.main(["resource-live", "--all", "--json"])
    assert code3 == 0
    out3 = json.loads(capsys.readouterr().out)
    assert "host:heavy" in out3
    assert "cdp:perplexity" in out3
    assert "cdp:chatgpt" in out3
    assert "cdp:gemini" in out3
    assert out3["cdp:perplexity"]["live_counts"]["ACTIVE"] == 1
    assert out3["cdp:chatgpt"]["live_counts"]["ACTIVE"] == 1

