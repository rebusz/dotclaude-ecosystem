"""Unit tests for ConductorScheduler determinism, priority, and dependency checks."""

import pathlib
import pytest

from scripts.conductor_commands import ConductorCommandProcessor
from scripts.conductor_model import CommandEnvelope, WorkItemState
from scripts.conductor_scheduler import ConductorScheduler
from scripts.conductor_store import ConductorStore


@pytest.fixture
def scheduler(tmp_path: pathlib.Path) -> ConductorScheduler:
    store = ConductorStore(root_dir=tmp_path)
    return ConductorScheduler(store=store)


def test_deterministic_scheduler_ordering(scheduler: ConductorScheduler):
    store = scheduler.store
    processor = ConductorCommandProcessor(store=store)

    # Enqueue Item A (R1, Priority 50)
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_a",
            command_type="enqueue",
            payload={
                "idempotency_key": "key_a",
                "title": "Task A",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/a.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
                "priority": 50,
            },
            idempotency_key="idemp_a",
        )
    )

    # Enqueue Item B (R1, Priority 80 - Higher priority)
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_b",
            command_type="enqueue",
            payload={
                "idempotency_key": "key_b",
                "title": "Task B",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/b.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
                "priority": 80,
            },
            idempotency_key="idemp_b",
        )
    )

    item_a = store.get_work_item_by_idempotency_key("key_a")
    item_b = store.get_work_item_by_idempotency_key("key_b")

    # Transition both to READY
    store.transition_work_item_state(item_a.work_item_id, WorkItemState.READY, "operator", "TEST_READY")
    store.transition_work_item_state(item_b.work_item_id, WorkItemState.READY, "operator", "TEST_READY")

    selected, rejected = scheduler.select_next_work_item()
    assert selected is not None
    assert selected.work_item_id == item_b.work_item_id
    assert len(rejected) == 1
    assert rejected[0]["work_item_id"] == item_a.work_item_id


def test_scheduler_dependency_blocking(scheduler: ConductorScheduler):
    store = scheduler.store
    processor = ConductorCommandProcessor(store=store)

    # Item Parent
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_p",
            command_type="enqueue",
            payload={
                "idempotency_key": "key_parent",
                "title": "Parent Task",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/p.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
            },
            idempotency_key="idemp_p",
        )
    )
    parent_item = store.get_work_item_by_idempotency_key("key_parent")

    # Item Child (depends on Parent)
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_c",
            command_type="enqueue",
            payload={
                "idempotency_key": "key_child",
                "title": "Child Task",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/c.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "engineering_plan_lifecycle",
                "dependency_ids": [parent_item.work_item_id],
                "priority": 100,  # Higher priority, but blocked by dependency
            },
            idempotency_key="idemp_c",
        )
    )
    child_item = store.get_work_item_by_idempotency_key("key_child")

    # Set both to READY
    store.transition_work_item_state(parent_item.work_item_id, WorkItemState.READY, "operator", "TEST_READY")
    store.transition_work_item_state(child_item.work_item_id, WorkItemState.READY, "operator", "TEST_READY")

    selected, rejected = scheduler.select_next_work_item()
    assert selected is not None
    assert selected.work_item_id == parent_item.work_item_id
    assert any(r["work_item_id"] == child_item.work_item_id and r["reason_code"] == "DEPENDENCY_UNSATISFIED" for r in rejected)


def test_scheduler_surfaces_host_resource_conflict_before_priority(scheduler: ConductorScheduler):
    processor = ConductorCommandProcessor(store=scheduler.store)
    processor.process_envelope(
        CommandEnvelope(
            command_id="cmd_heavy",
            command_type="enqueue",
            payload={
                "idempotency_key": "key_heavy",
                "title": "Heavy Task",
                "repo_id": "dotclaude-ecosystem",
                "repo_path": "D:/dotclaude/dotclaude-ecosystem",
                "plan_path": "design/plans/heavy.md",
                "risk_class": "R1",
                "workflow": "fwf",
                "requested_terminal_stage": "merged",
                "job_kind": "pytest_full",
                "priority": 100,
            },
            idempotency_key="idemp_heavy",
        )
    )
    item = scheduler.store.get_work_item_by_idempotency_key("key_heavy")
    scheduler.store.transition_work_item_state(item.work_item_id, WorkItemState.READY, "operator", "TEST_READY")
    active = scheduler.resources.request(
        purpose="pytest_heavy",
        attempt_id="resource-active",
        agent_instance="resource-agent",
    )

    selected, rejected = scheduler.select_next_work_item()
    assert selected is None
    assert any(
        entry["work_item_id"] == item.work_item_id and entry["reason_code"] == "HOST_RESOURCE_BUSY"
        for entry in rejected
    )
    scheduler.resources.release(active["request_id"])
