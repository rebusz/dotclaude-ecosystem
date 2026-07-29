"""Unit tests for conductor_model entity definitions and state transitions."""

import pytest
from scripts.conductor_model import (
    WorkItem,
    WorkItemState,
    can_transition,
)


def test_work_item_creation_and_validation():
    item = WorkItem(
        work_item_id="wi_123",
        idempotency_key="key_123",
        title="Test Work Item",
        repo_id="dotclaude-ecosystem",
        repo_path="D:/dotclaude/dotclaude-ecosystem",
        plan_path="design/plans/test.md",
        risk_class="R2",
        workflow="fwf",
        requested_terminal_stage="merged",
        job_kind="engineering_plan_lifecycle",
    )

    item.validate()
    assert item.state == WorkItemState.DISCOVERED
    assert item.execution_budget.max_attempts == 1

    d = item.to_dict()
    assert d["work_item_id"] == "wi_123"
    assert d["risk_class"] == "R2"

    rebuilt = WorkItem.from_dict(d)
    assert rebuilt.work_item_id == item.work_item_id
    assert rebuilt.state == WorkItemState.DISCOVERED


def test_work_item_invalid_fields():
    item = WorkItem(
        work_item_id="",
        idempotency_key="key_123",
        title="Test Work Item",
        repo_id="dotclaude-ecosystem",
        repo_path="D:/dotclaude/dotclaude-ecosystem",
        plan_path="design/plans/test.md",
        risk_class="INVALID",
        workflow="fwf",
        requested_terminal_stage="merged",
        job_kind="engineering_plan_lifecycle",
    )

    with pytest.raises(ValueError):
        item.validate()


def test_state_transitions():
    assert can_transition(WorkItemState.DISCOVERED, WorkItemState.QUEUED)
    assert can_transition(WorkItemState.QUEUED, WorkItemState.READY)
    assert can_transition(WorkItemState.READY, WorkItemState.CLAIMED)
    assert can_transition(WorkItemState.CLAIMED, WorkItemState.DISPATCHING)
    assert can_transition(WorkItemState.DISPATCHING, WorkItemState.RUNNING)
    assert can_transition(WorkItemState.RUNNING, WorkItemState.COMPLETED)

    # Invalid transitions
    assert not can_transition(WorkItemState.DISCOVERED, WorkItemState.COMPLETED)
    assert not can_transition(WorkItemState.COMPLETED, WorkItemState.READY)
    assert not can_transition(WorkItemState.CANCELLED, WorkItemState.RUNNING)
