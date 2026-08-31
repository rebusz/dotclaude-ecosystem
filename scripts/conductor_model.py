"""Domain entities, schemas, state machine transitions, and reason code registry for TruthDeck Conductor.

All environment variable references use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

# Schema Constants
SCHEMA_WORK_ITEM = "conductor.work-item.v1"
SCHEMA_ATTEMPT = "conductor.attempt.v1"
SCHEMA_CLAIM = "conductor.claim.v1"
SCHEMA_LEASE = "conductor.lease.v1"
SCHEMA_CHECKPOINT = "conductor.checkpoint.v1"
SCHEMA_EVENT = "conductor.event.v1"
SCHEMA_AUTHORIZATION = "conductor.authorization.v1"
SCHEMA_STATUS = "conductor.status.v1"
SCHEMA_COMMAND = "conductor.command.v1"
SCHEMA_RECEIPT = "conductor.receipt.v1"
SCHEMA_RESOURCE_REQUEST = "conductor.resource-request.v1"
SCHEMA_RESOURCE_LEASE = "conductor.resource-lease.v1"
SCHEMA_RESOURCE_EVENT = "conductor.resource-event.v1"


class WorkItemState(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    HOLD = "HOLD"
    READY = "READY"
    CLAIMED = "CLAIMED"
    DISPATCHING = "DISPATCHING"
    RUNNING = "RUNNING"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    DISPATCH_UNKNOWN = "DISPATCH_UNKNOWN"
    QUARANTINED = "QUARANTINED"


# Valid State Transitions Map
VALID_TRANSITIONS: Dict[WorkItemState, Set[WorkItemState]] = {
    WorkItemState.DISCOVERED: {WorkItemState.QUEUED, WorkItemState.CANCELLED},
    WorkItemState.QUEUED: {WorkItemState.HOLD, WorkItemState.READY, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.HOLD: {WorkItemState.READY, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.READY: {WorkItemState.CLAIMED, WorkItemState.HOLD, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.CLAIMED: {WorkItemState.DISPATCHING, WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.DISPATCHING: {WorkItemState.RUNNING, WorkItemState.DISPATCH_UNKNOWN, WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.RUNNING: {WorkItemState.WAITING_EXTERNAL, WorkItemState.REVIEW, WorkItemState.COMPLETED, WorkItemState.BLOCKED, WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.WAITING_EXTERNAL: {WorkItemState.RUNNING, WorkItemState.BLOCKED, WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.REVIEW: {WorkItemState.COMPLETED, WorkItemState.BLOCKED, WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.RECOVERY_REQUIRED: {WorkItemState.READY, WorkItemState.HOLD, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.DISPATCH_UNKNOWN: {WorkItemState.RECOVERY_REQUIRED, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.BLOCKED: {WorkItemState.READY, WorkItemState.HOLD, WorkItemState.CANCELLED, WorkItemState.QUARANTINED},
    WorkItemState.COMPLETED: set(),  # Terminal
    WorkItemState.CANCELLED: set(),  # Terminal
    WorkItemState.QUARANTINED: set(),  # Terminal
}


class ReasonCode(str, Enum):
    ADMISSION_OPERATOR_ENQUEUE = "ADMISSION_OPERATOR_ENQUEUE"
    ADMISSION_RECURRING_MONITOR = "ADMISSION_RECURRING_MONITOR"
    ADMISSION_WORKFLOW_CONTINUATION = "ADMISSION_WORKFLOW_CONTINUATION"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    AUTHORIZATION_MISSING = "AUTHORIZATION_MISSING"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_SCOPE_MISMATCH = "AUTHORIZATION_SCOPE_MISMATCH"
    EVIDENCE_CHECKPOINT_MISSING = "EVIDENCE_CHECKPOINT_MISSING"
    EVIDENCE_CHECKPOINT_STALE = "EVIDENCE_CHECKPOINT_STALE"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"
    HOST_ADAPTER_MISSING = "HOST_ADAPTER_MISSING"
    HOST_ADAPTER_ERROR = "HOST_ADAPTER_ERROR"
    HOST_QUOTA_EXHAUSTED = "HOST_QUOTA_EXHAUSTED"
    HOST_CLAIM_SPAM_HOLD = "HOST_CLAIM_SPAM_HOLD"
    BUDGET_WALL_TIME_EXHAUSTED = "BUDGET_WALL_TIME_EXHAUSTED"
    BUDGET_MAX_ATTEMPTS_EXHAUSTED = "BUDGET_MAX_ATTEMPTS_EXHAUSTED"
    OPERATOR_CANCELLED = "OPERATOR_CANCELLED"
    OPERATOR_PAUSED = "OPERATOR_PAUSED"
    CORRUPT_STATE_QUARANTINED = "CORRUPT_STATE_QUARANTINED"
    STORAGE_EXHAUSTED = "STORAGE_EXHAUSTED"
    SLOT_KEY_BUSY = "SLOT_KEY_BUSY"


def current_utc_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionBudget:
    max_attempts: int = 1
    max_wall_seconds: int = 7200
    max_cost_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionBudget:
        return cls(
            max_attempts=data.get("max_attempts", 1),
            max_wall_seconds=data.get("max_wall_seconds", 7200),
            max_cost_usd=data.get("max_cost_usd"),
        )


@dataclass
class WorkItem:
    work_item_id: str
    idempotency_key: str
    title: str
    repo_id: str
    repo_path: str
    plan_path: str
    risk_class: str  # R0, R1, R2, R3
    workflow: str  # fwf, fwp
    requested_terminal_stage: str  # e.g., merged
    job_kind: str  # e.g., engineering_plan_lifecycle
    priority: int = 50
    dependency_ids: List[str] = field(default_factory=list)
    authority_requirement: str = "standing_r2_go"
    execution_budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    scope_digest_sha256: str = ""
    context_digest_sha256: str = ""
    state: WorkItemState = WorkItemState.DISCOVERED
    created_at_utc: str = field(default_factory=current_utc_iso)
    created_by: str = "operator"
    schema_version: str = SCHEMA_WORK_ITEM

    def validate(self) -> None:
        if not self.work_item_id or not self.idempotency_key:
            raise ValueError("work_item_id and idempotency_key are required")
        if self.risk_class not in {"R0", "R1", "R2", "R3"}:
            raise ValueError(f"Invalid risk class: {self.risk_class}")
        if self.workflow not in {"fwf", "fwp"}:
            raise ValueError(f"Invalid workflow: {self.workflow}")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value if isinstance(self.state, WorkItemState) else self.state
        d["execution_budget"] = self.execution_budget.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkItem:
        budget_data = data.get("execution_budget", {})
        budget = ExecutionBudget.from_dict(budget_data) if isinstance(budget_data, dict) else budget_data
        state_val = data.get("state", WorkItemState.DISCOVERED)
        if isinstance(state_val, str):
            state_val = WorkItemState(state_val)
        return cls(
            work_item_id=data.get("work_item_id", f"wi_{uuid.uuid4().hex[:12]}"),
            idempotency_key=data.get("idempotency_key", f"idemp_{uuid.uuid4().hex[:12]}"),
            title=data.get("title", "Untitled Task"),
            repo_id=data.get("repo_id", "dotclaude-ecosystem"),
            repo_path=data.get("repo_path", ""),
            plan_path=data.get("plan_path", ""),
            risk_class=data.get("risk_class", "R1"),
            workflow=data.get("workflow", "fwf"),
            requested_terminal_stage=data.get("requested_terminal_stage", "merged"),
            job_kind=data.get("job_kind", "engineering_plan_lifecycle"),
            priority=data.get("priority", 50),
            dependency_ids=data.get("dependency_ids", []),
            authority_requirement=data.get("authority_requirement", "standing_r2_go"),
            execution_budget=budget,
            scope_digest_sha256=data.get("scope_digest_sha256", ""),
            context_digest_sha256=data.get("context_digest_sha256", ""),
            state=state_val,
            created_at_utc=data.get("created_at_utc", current_utc_iso()),
            created_by=data.get("created_by", "operator"),
            schema_version=data.get("schema_version", SCHEMA_WORK_ITEM),
        )


@dataclass
class Attempt:
    attempt_id: str
    work_item_id: str
    attempt_number: int
    agent_host: str
    agent_instance: str
    adapter_version: str
    worktree_path: str
    branch_name: str
    base_head_sha: str
    dispatch_idempotency_key: str
    status: str = "IN_PROGRESS"
    reason_code: Optional[str] = None
    started_at_utc: str = field(default_factory=current_utc_iso)
    ended_at_utc: Optional[str] = None
    schema_version: str = SCHEMA_ATTEMPT

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Claim:
    claim_id: str
    work_item_id: str
    attempt_id: str
    claimed_by_host: str
    claimed_at_utc: str = field(default_factory=current_utc_iso)
    lease_ttl_seconds: int = 300
    schema_version: str = SCHEMA_CLAIM

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Lease:
    lease_id: str
    attempt_id: str
    agent_instance: str
    heartbeat_sequence: int
    expires_at_utc: str
    last_heartbeat_utc: str = field(default_factory=current_utc_iso)
    schema_version: str = SCHEMA_LEASE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HostResourceRequestState(str, Enum):
    QUEUED = "QUEUED"
    ACTIVE = "ACTIVE"
    INHERITED = "INHERITED"
    RELEASED = "RELEASED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    QUARANTINED = "QUARANTINED"


@dataclass
class HostResourceRequest:
    request_id: str
    idempotency_key: str
    resource_key: str
    purpose: str
    attempt_id: str
    agent_instance: str
    state: HostResourceRequestState = HostResourceRequestState.QUEUED
    priority: int = 50
    parent_lease_id: Optional[str] = None
    command_sha256: str = ""
    created_at_utc: str = field(default_factory=current_utc_iso)
    released_at_utc: Optional[str] = None
    reason_code: Optional[str] = None
    slot_key: str = ""
    owner_process_pid: Optional[int] = None
    owner_process_start_time: Optional[float] = None
    owner_identity_source: str = "UNRECORDED"
    owner_last_seen_at_utc: Optional[str] = None
    schema_version: str = SCHEMA_RESOURCE_REQUEST

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value if isinstance(self.state, HostResourceRequestState) else self.state
        return d


@dataclass
class HostResourceLease:
    lease_id: str
    request_id: str
    resource_key: str
    attempt_id: str
    agent_instance: str
    heartbeat_sequence: int
    expires_at_utc: str
    last_heartbeat_utc: str = field(default_factory=current_utc_iso)
    process_pid: Optional[int] = None
    process_start_time: Optional[float] = None
    schema_version: str = SCHEMA_RESOURCE_LEASE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HostResourcePool:
    resource_key: str
    capacity: int = 1
    enabled: bool = True
    schema_version: str = "conductor.resource-pool.v1"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCheckpoint:
    checkpoint_id: str
    work_item_id: str
    attempt_id: Optional[str]
    boundary: str  # pre_claim, pre_dispatch, checkpoint, pre_review, pre_complete
    snapshot_path: str
    snapshot_sha256: str
    snapshot_id: str
    required_gate: str
    observed_gate_state: str  # PASS, HOLD, BLOCKED, UNKNOWN, NOT_APPLICABLE
    observed_head: Optional[str] = None
    recorded_at_utc: str = field(default_factory=current_utc_iso)
    schema_version: str = SCHEMA_CHECKPOINT

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EventRecord:
    event_id: str
    work_item_id: str
    attempt_id: Optional[str]
    previous_state: str
    next_state: str
    actor_identity: str
    reason_code: str
    recorded_at_utc: str = field(default_factory=current_utc_iso)
    details: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_EVENT

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuthorizationRecord:
    authorization_id: str
    work_item_id: str
    scope_digest_sha256: str
    risk_class: str
    authorized_workflow: str
    permitted_terminal_stage: str
    issued_at_utc: str = field(default_factory=current_utc_iso)
    expires_at_utc: Optional[str] = None
    operator_identity: str = "operator"
    interactive_provenance_proven: bool = False
    schema_version: str = SCHEMA_AUTHORIZATION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CommandEnvelope:
    command_id: str
    command_type: str  # enqueue, authorize, claim, heartbeat, checkpoint, complete, block, cancel, status, reconcile, export
    payload: Dict[str, Any]
    idempotency_key: str
    issued_at_utc: str = field(default_factory=current_utc_iso)
    schema_version: str = SCHEMA_COMMAND

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Receipt:
    receipt_id: str
    command_id: str
    idempotency_key: str
    status: str  # SUCCESS, REJECTED, PENDING_DELIVERY, ERROR
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    processed_at_utc: str = field(default_factory=current_utc_iso)
    schema_version: str = SCHEMA_RECEIPT

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def can_transition(current: WorkItemState, target: WorkItemState) -> bool:
    """Validate whether current -> target state transition is allowed."""
    valid_targets = VALID_TRANSITIONS.get(current, set())
    return target in valid_targets
