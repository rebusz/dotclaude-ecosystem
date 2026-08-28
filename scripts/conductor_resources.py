"""Capacity-one host resource admission and the bounded pytest consumer.

This module is deliberately separate from Work Item leases.  A Work Item does
not own ``host:heavy``; only a named heavy consumer acquires that pool.  Child
process supervision keeps the retained ``Popen`` handle as the authority for
liveness and never polls WMI or a process table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import pathlib
import psutil
import re
import subprocess
import time
from typing import Any, Dict, Mapping, Optional, Sequence
import uuid

from scripts.conductor_model import (
    HostResourcePool,
    HostResourceRequest,
    HostResourceRequestState,
    current_utc_iso,
)
from scripts.conductor_store import ConductorStore


RESOURCE_KEY = "host:heavy"
LEASE_ENV = "TDCONDUCTOR_LEASE_ID"
DEFAULT_LEASE_TTL_SECONDS = 300
CDP_POOLS = frozenset({"cdp:perplexity", "cdp:chatgpt", "cdp:gemini"})
DEFAULT_POOL_CAPACITIES = {
    "host:heavy": 1,
    "cdp:perplexity": 3,
    "cdp:chatgpt": 3,
    "cdp:gemini": 1,
}
ROLE_TO_RESOURCE_KEY = {
    "chrome_ppl": "cdp:perplexity",
    "chrome_gpt": "cdp:chatgpt",
    "chrome_gemini": "cdp:gemini",
}
PURPOSE_TO_RESOURCE_KEY = {
    "pytest_full": "host:heavy",
    "pytest_heavy": "host:heavy",
    "pytest_focused": "host:heavy",
    "playwright": "host:heavy",
    "cdp_perplexity": "cdp:perplexity",
    "cdp_chatgpt": "cdp:chatgpt",
    "cdp_gemini": "cdp:gemini",
}
VALID_PURPOSES = frozenset(
    {
        "pytest_full",
        "pytest_heavy",
        "pytest_focused",
        "playwright",
        "cdp_provider",
        "cdp_perplexity",
        "cdp_chatgpt",
        "cdp_gemini",
    }
)


def resolve_resource_key(
    purpose: Optional[str] = None,
    role: Optional[str] = None,
    resource_key: Optional[str] = None,
) -> str:
    """Resolve target resource pool from explicit key, CDP role, or purpose."""
    if resource_key:
        return resource_key
    if role and role in ROLE_TO_RESOURCE_KEY:
        return ROLE_TO_RESOURCE_KEY[role]
    if purpose and purpose in PURPOSE_TO_RESOURCE_KEY:
        return PURPOSE_TO_RESOURCE_KEY[purpose]
    return RESOURCE_KEY
_PYTHON_EXECUTABLE_RE = re.compile(r"python(?:\d+(?:\.\d+)?)?(?:\.exe)?$", re.IGNORECASE)
_PYTEST_OPTION_VALUES = frozenset(
    {
        "-c",
        "--config-file",
        "--confcutdir",
        "--cov",
        "--cov-config",
        "--cov-report",
        "--cov-fail-under",
        "--basetemp",
        "--rootdir",
        "--junitxml",
        "--override-ini",
        "-k",
        "--keyword",
        "-m",
        "--markexpr",
        "--maxfail",
        "--tb",
        "--trace-config",
        "--log-cli-level",
        "--log-file",
        "--durations",
        "--timeout",
        "--timeout-method",
    }
)
_PYTEST_FLAG_OPTIONS = frozenset(
    {
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "-x",
        "--exitfirst",
        "--lf",
        "--last-failed",
        "--ff",
        "--failed-first",
        "--strict-markers",
        "--strict-config",
        "--collect-only",
        "--setup-show",
        "--no-header",
        "--no-summary",
        "--disable-warnings",
        "--capture=sys",
        "--capture=fd",
        "--capture=no",
    }
)
_CHILD_ENV_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PYTHONHOME",
        "PYTHONPATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)


class ResourceAdmissionError(RuntimeError):
    """Base error for fail-closed resource admission."""


class ResourceBusyError(ResourceAdmissionError):
    """Raised when a request cannot safely consume the capacity-one pool."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def classify_pytest_invocation(
    pytest_args: Sequence[str], cwd: str | pathlib.Path | None = None
) -> str:
    """Classify a pytest invocation conservatively before acquiring capacity."""
    if isinstance(pytest_args, (str, bytes)) or not isinstance(pytest_args, Sequence):
        return "pytest_heavy_unknown"
    args = [str(arg) for arg in pytest_args]
    if args and args[0] == "--":
        args = args[1:]
    lowered = [arg.lower() for arg in args]
    heavy_markers = ("integration", "stress", "benchmark", "xdist")
    if any(marker in arg for arg in lowered for marker in heavy_markers):
        return "pytest_heavy"
    if any(
        arg in {"-n", "--numprocesses", "--dist", "--maxprocesses", "--workers"}
        or arg.startswith("-n")
        for arg in lowered
    ):
        return "pytest_heavy"

    targets: list[str] = []
    skip_next = False
    unknown_option = False
    for arg in args:
        lower = arg.lower()
        if skip_next:
            skip_next = False
            continue
        if lower in _PYTEST_OPTION_VALUES:
            skip_next = True
            continue
        if lower.startswith(tuple(f"{option}=" for option in _PYTEST_OPTION_VALUES)):
            continue
        if lower in _PYTEST_FLAG_OPTIONS or lower == "--":
            continue
        if lower.startswith("-"):
            unknown_option = True
            continue
        targets.append(arg)

    if unknown_option:
        return "pytest_heavy_unknown"
    if not targets or len(targets) > 1:
        return "pytest_full"
    target = targets[0]
    if "::" in target:
        return "pytest_focused" if target.split("::", 1)[0].lower().endswith(".py") else "pytest_heavy_unknown"
    if target.lower().endswith(".py"):
        return "pytest_focused"
    if cwd is not None:
        try:
            if (pathlib.Path(cwd).resolve() / target).is_dir():
                return "pytest_full"
        except OSError:
            pass
    return "pytest_heavy_unknown"


class HostResourceManager:
    """Single-writer resource admission over :class:`ConductorStore`."""

    def __init__(self, store: ConductorStore, resource_key: str = RESOURCE_KEY):
        self.store = store
        self.resource_key = resource_key
        pool = self.store.get_resource_pool(resource_key)
        if pool is None:
            default_capacity = DEFAULT_POOL_CAPACITIES.get(resource_key, 1)
            # HRL-R2 intentionally has no environment-configurable capacity.
            self.store.save_resource_pool(
                HostResourcePool(resource_key=resource_key, capacity=default_capacity, enabled=True)
            )

    def request(
        self,
        *,
        purpose: str,
        attempt_id: str,
        agent_instance: str,
        slot_key: str = "",
        idempotency_key: Optional[str] = None,
        command_sha256: str = "",
        priority: int = 50,
        parent_lease_id: Optional[str] = None,
        environment: Optional[Mapping[str, str]] = None,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        actor: str = "resource-adapter",
    ) -> Dict[str, Any]:
        """Admit a named consumer, queue it, or inherit its ancestor lease.

        The entire decision and lease creation occurs under ``BEGIN IMMEDIATE``
        so two independent callers cannot both observe capacity as available.
        """
        self._validate_request(purpose, attempt_id, agent_instance, lease_ttl_seconds, priority, self.resource_key)
        idempotency_key = idempotency_key or f"resource_{uuid.uuid4().hex}"
        slot_key = str(slot_key or "").strip()
        inherited_id = parent_lease_id or (environment or {}).get(LEASE_ENV)
        inherited_rejection: Optional[str] = None
        now = _now()
        now_iso = _iso(now)

        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM host_resource_requests WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                request = self.store._row_to_resource_request(existing)
                return self._request_result(conn, request, replayed=True)

            pool = conn.execute(
                "SELECT * FROM host_resource_pools WHERE resource_key = ?", (self.resource_key,)
            ).fetchone()
            if not pool or not bool(pool["enabled"]):
                raise ResourceAdmissionError("HOST_RESOURCE_DISABLED")
            capacity = int(pool["capacity"])
            if capacity < 1 or (self.resource_key == "host:heavy" and capacity != 1):
                raise ResourceAdmissionError("HOST_RESOURCE_CAPACITY_INVALID")

            request_id = f"rr_{uuid.uuid4().hex[:12]}"

            if inherited_id:
                parent = conn.execute(
                    """
                    SELECT l.*, r.state AS request_state
                    FROM host_resource_leases l
                    JOIN host_resource_requests r ON r.request_id = l.request_id
                    WHERE l.lease_id = ? AND l.resource_key = ?
                    """,
                    (inherited_id, self.resource_key),
                ).fetchone()
                if not parent or parent["request_state"] != HostResourceRequestState.ACTIVE.value:
                    inherited_rejection = "INHERITED_LEASE_INVALID"
                    inherited_id = None
                elif parent["expires_at_utc"] <= now_iso:
                    inherited_rejection = "INHERITED_LEASE_EXPIRED"
                    inherited_id = None
                else:
                    child_count = conn.execute(
                        """
                        SELECT COUNT(*) FROM host_resource_requests
                        WHERE parent_lease_id = ? AND state = ?
                        """,
                        (inherited_id, HostResourceRequestState.INHERITED.value),
                    ).fetchone()[0]
                    if child_count:
                        self._insert_request(
                            conn,
                            HostResourceRequest(
                                request_id=request_id,
                                idempotency_key=idempotency_key,
                                resource_key=self.resource_key,
                                purpose=purpose,
                                attempt_id=attempt_id,
                                agent_instance=agent_instance,
                                state=HostResourceRequestState.QUARANTINED,
                                priority=priority,
                                parent_lease_id=inherited_id,
                                command_sha256=command_sha256,
                                reason_code="INHERITED_CHILD_BUSY",
                                slot_key=slot_key,
                            ),
                        )
                        self._event(conn, request_id, None, None, HostResourceRequestState.QUARANTINED.value, actor, "INHERITED_CHILD_BUSY")
                        # Commit the refusal ledger before surfacing the
                        # exception; otherwise the connection context would
                        # roll the quarantine row back with the failed call.
                        conn.commit()
                        raise ResourceBusyError("INHERITED_CHILD_BUSY")

                    request = HostResourceRequest(
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                        resource_key=self.resource_key,
                        purpose=purpose,
                        attempt_id=attempt_id,
                        agent_instance=agent_instance,
                        state=HostResourceRequestState.INHERITED,
                        priority=priority,
                        parent_lease_id=inherited_id,
                        command_sha256=command_sha256,
                        slot_key=slot_key,
                    )
                    self._insert_request(conn, request)
                    self._event(conn, request_id, inherited_id, None, request.state.value, actor, "LEASE_INHERITED")
                    return self._request_result(conn, request, lease_id=inherited_id)

            active_or_fenced = conn.execute(
                """
                SELECT r.state, r.slot_key FROM host_resource_requests r
                WHERE r.resource_key = ? AND r.state IN (?, ?)
                """,
                (
                    self.resource_key,
                    HostResourceRequestState.ACTIVE.value,
                    HostResourceRequestState.RECOVERY_REQUIRED.value,
                ),
            ).fetchall()

            active_or_fenced_count = len(active_or_fenced)
            active_slot_keys = {
                row["slot_key"] for row in active_or_fenced
                if row["slot_key"]
            }

            capacity_full = (active_or_fenced_count >= capacity)
            slot_busy = bool(slot_key and slot_key in active_slot_keys)

            if capacity_full:
                state = HostResourceRequestState.QUEUED
                reason = inherited_rejection or "HOST_RESOURCE_BUSY"
            elif slot_busy:
                state = HostResourceRequestState.QUEUED
                reason = inherited_rejection or "SLOT_KEY_BUSY"
            else:
                state = HostResourceRequestState.ACTIVE
                reason = inherited_rejection or "HOST_RESOURCE_ADMITTED"

            request = HostResourceRequest(
                request_id=request_id,
                idempotency_key=idempotency_key,
                resource_key=self.resource_key,
                purpose=purpose,
                attempt_id=attempt_id,
                agent_instance=agent_instance,
                state=state,
                priority=priority,
                command_sha256=command_sha256,
                reason_code=reason,
                slot_key=slot_key,
            )
            self._insert_request(conn, request)
            lease_id: Optional[str] = None
            if state == HostResourceRequestState.ACTIVE:
                lease_id = self._create_lease_locked(
                    conn, request, lease_ttl_seconds=lease_ttl_seconds, now=now
                )
            self._event(conn, request_id, lease_id, None, state.value, actor, reason)
            return self._request_result(conn, request, lease_id=lease_id)

    def heartbeat(
        self, lease_id: str, sequence: int, *, lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS
    ) -> Dict[str, Any]:
        if sequence < 1 or lease_ttl_seconds < 1:
            raise ValueError("heartbeat sequence and TTL must be positive")
        now = _now()
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT l.*, r.state AS request_state FROM host_resource_leases l
                JOIN host_resource_requests r ON r.request_id = l.request_id
                WHERE l.lease_id = ?
                """,
                (lease_id,),
            ).fetchone()
            if not row or row["request_state"] != HostResourceRequestState.ACTIVE.value:
                raise ResourceAdmissionError("RESOURCE_LEASE_NOT_ACTIVE")
            if sequence <= int(row["heartbeat_sequence"]):
                raise ValueError("HEARTBEAT_OUT_OF_ORDER")
            expires = _iso(now + timedelta(seconds=lease_ttl_seconds))
            conn.execute(
                """
                UPDATE host_resource_leases
                SET heartbeat_sequence = ?, expires_at_utc = ?, last_heartbeat_utc = ?
                WHERE lease_id = ?
                """,
                (sequence, expires, _iso(now), lease_id),
            )
            return {"lease_id": lease_id, "heartbeat_sequence": sequence, "expires_at_utc": expires}

    def release(self, request_id: str, *, actor: str = "resource-adapter", reason: str = "RESOURCE_RELEASED") -> Dict[str, Any]:
        """Release a request and promote the oldest queued request if safe."""
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM host_resource_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if not row:
                raise ResourceAdmissionError("RESOURCE_REQUEST_NOT_FOUND")
            old_state = row["state"]
            if old_state in {
                HostResourceRequestState.RELEASED.value,
                HostResourceRequestState.QUARANTINED.value,
            }:
                return {"request_id": request_id, "status": "ALREADY_RELEASED", "state": old_state}
            if old_state == HostResourceRequestState.RECOVERY_REQUIRED.value:
                # Expiry is an ambiguity boundary.  A caller must prove the
                # owner is gone and explicitly reconcile it before capacity
                # can be released; releasing here would create a split-brain
                # overlap with an unknown child.
                raise ResourceAdmissionError("RECOVERY_REQUIRED_RELEASE_REFUSED")
            if old_state == HostResourceRequestState.ACTIVE.value:
                active_lease = conn.execute(
                    "SELECT lease_id FROM host_resource_leases WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                inherited_children = conn.execute(
                    """
                    SELECT COUNT(*) FROM host_resource_requests
                    WHERE parent_lease_id = ? AND state = ?
                    """,
                    (
                        active_lease["lease_id"] if active_lease else "",
                        HostResourceRequestState.INHERITED.value,
                    ),
                ).fetchone()[0]
                if inherited_children:
                    raise ResourceBusyError("INHERITED_CHILD_ACTIVE")
            now_iso = current_utc_iso()
            conn.execute(
                "UPDATE host_resource_requests SET state = ?, released_at_utc = ?, reason_code = ? WHERE request_id = ?",
                (HostResourceRequestState.RELEASED.value, now_iso, reason, request_id),
            )
            lease_row = conn.execute(
                "SELECT lease_id FROM host_resource_leases WHERE request_id = ?", (request_id,)
            ).fetchone()
            lease_id = lease_row["lease_id"] if lease_row else row["parent_lease_id"]
            self._event(conn, request_id, lease_id, old_state, HostResourceRequestState.RELEASED.value, actor, reason)
            promoted = self._promote_locked(conn, resource_key=row["resource_key"], actor=actor)
            return {"request_id": request_id, "status": "RELEASED", "promoted": promoted}

    def reconcile(self, *, dry_run: bool = False, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Mark expired resource leases recovery-required; never auto-retry them."""
        now = now or _now()
        now_iso = _iso(now)
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT l.lease_id, l.request_id, r.state FROM host_resource_leases l
                JOIN host_resource_requests r ON r.request_id = l.request_id
                WHERE r.state = ? AND l.expires_at_utc < ?
                """,
                (HostResourceRequestState.ACTIVE.value, now_iso),
            ).fetchall()
            if not dry_run:
                for row in rows:
                    conn.execute(
                        "UPDATE host_resource_requests SET state = ?, reason_code = ? WHERE request_id = ?",
                        (HostResourceRequestState.RECOVERY_REQUIRED.value, "LEASE_EXPIRED", row["request_id"]),
                    )
                    self._event(
                        conn,
                        row["request_id"],
                        row["lease_id"],
                        row["state"],
                        HostResourceRequestState.RECOVERY_REQUIRED.value,
                        "reconciler",
                        "LEASE_EXPIRED",
                    )
            return {
                "expired_count": len(rows),
                "request_ids": [row["request_id"] for row in rows],
                "dry_run": dry_run,
            }

    def recover(
        self,
        request_id: str,
        *,
        operator_attestation: bool = False,
        reason: str = "",
        actor: str = "resource-recovery",
    ) -> Dict[str, Any]:
        """Clear one RECOVERY_REQUIRED request once its owner is proven gone.

        ``release`` refuses this state on purpose: an expired lease is an
        ambiguity boundary, not a death certificate.  Recovery is the explicit
        crossing of that boundary and it demands evidence.

        A lease that recorded its bounded child yields that evidence on its own:
        the pid is gone, or the pid was reused and its start time no longer
        matches the one recorded at admission.  A lease that never recorded a
        child - a consumer that took capacity and died before attaching one -
        cannot be adjudicated by the harness at all, so an operator must attest
        the owner is gone and say why.  Attestation never overrides a process
        that is still running.  Both paths write their evidence into the event
        ledger, so a recovered slot always names who freed it and on what basis.
        """
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM host_resource_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if not row:
                raise ResourceAdmissionError("RESOURCE_REQUEST_NOT_FOUND")
            if row["state"] != HostResourceRequestState.RECOVERY_REQUIRED.value:
                raise ResourceAdmissionError("RESOURCE_REQUEST_NOT_RECOVERABLE")

            lease_row = conn.execute(
                "SELECT * FROM host_resource_leases WHERE request_id = ?", (request_id,)
            ).fetchone()
            lease_id = lease_row["lease_id"] if lease_row else row["parent_lease_id"]

            inherited_children = conn.execute(
                """
                SELECT COUNT(*) FROM host_resource_requests
                WHERE parent_lease_id = ? AND state = ?
                """,
                (lease_id or "", HostResourceRequestState.INHERITED.value),
            ).fetchone()[0]
            if inherited_children:
                # The split-brain the release refusal exists to prevent: the
                # parent is gone but a child still believes it holds capacity.
                raise ResourceBusyError("INHERITED_CHILD_ACTIVE")

            owner_gone, evidence = self._owner_liveness(
                lease_row["process_pid"] if lease_row else None,
                lease_row["process_start_time"] if lease_row else None,
            )
            if not owner_gone:
                if evidence == "OWNER_PROCESS_ALIVE":
                    raise ResourceAdmissionError("OWNER_PROCESS_ALIVE")
                if not operator_attestation:
                    raise ResourceAdmissionError("OWNER_LIVENESS_UNPROVEN")
                if not reason.strip():
                    raise ValueError("operator attestation requires a reason")
                evidence = "OPERATOR_ATTESTED"

            reason_code = "RECOVERY_ATTESTED" if evidence == "OPERATOR_ATTESTED" else "RECOVERY_OWNER_GONE"
            conn.execute(
                "UPDATE host_resource_requests SET state = ?, released_at_utc = ?, reason_code = ? WHERE request_id = ?",
                (HostResourceRequestState.RELEASED.value, current_utc_iso(), reason_code, request_id),
            )
            self._event(
                conn,
                request_id,
                lease_id,
                HostResourceRequestState.RECOVERY_REQUIRED.value,
                HostResourceRequestState.RELEASED.value,
                actor,
                reason_code,
                details={
                    "evidence": evidence,
                    "operator_reason": reason.strip(),
                    "recovered_lease_id": lease_id,
                },
            )
            promoted = self._promote_locked(conn, resource_key=row["resource_key"], actor=actor)
            return {
                "request_id": request_id,
                "status": "RECOVERED",
                "evidence": evidence,
                "attested": evidence == "OPERATOR_ATTESTED",
                "promoted": promoted,
            }

    @staticmethod
    def _owner_liveness(pid: Optional[int], start_time: Optional[float]) -> tuple[bool, str]:
        """Adjudicate a recorded lease process as gone, alive, or unrecorded."""
        if pid is None:
            return False, "OWNER_UNRECORDED"
        try:
            observed_start = psutil.Process(int(pid)).create_time()
        except (OSError, ValueError, psutil.Error):
            return True, "OWNER_PROCESS_GONE"
        if start_time is not None and abs(observed_start - float(start_time)) > 1.0:
            # Same pid, different process: the owner died and the OS reused it.
            return True, "OWNER_PID_REUSED"
        return False, "OWNER_PROCESS_ALIVE"

    def status(self) -> Dict[str, Any]:
        pool = self.store.get_resource_pool(self.resource_key)
        requests = self.store.list_resource_requests(resource_key=self.resource_key)
        leases = self.store.list_resource_leases(resource_key=self.resource_key)
        counts: Dict[str, int] = {}
        for request in requests:
            counts[request.state.value] = counts.get(request.state.value, 0) + 1
        return {
            "resource_key": self.resource_key,
            "capacity": pool.capacity if pool else 0,
            "enabled": bool(pool and pool.enabled),
            "active_units": counts.get(HostResourceRequestState.ACTIVE.value, 0),
            "queued": counts.get(HostResourceRequestState.QUEUED.value, 0),
            "recovery_required": counts.get(HostResourceRequestState.RECOVERY_REQUIRED.value, 0),
            "state_counts": counts,
            "storage": self.store.storage_status(),
            "requests": [request.to_dict() for request in requests],
            "leases": [lease.to_dict() for lease in leases],
        }

    def child_environment(
        self, lease_id: str, base_environment: Optional[Mapping[str, str]] = None
    ) -> Dict[str, str]:
        lease = self.store.get_resource_lease(lease_id)
        if not lease:
            raise ResourceAdmissionError("RESOURCE_LEASE_NOT_FOUND")
        request = self.store.get_resource_request(lease.request_id)
        if not request or request.state != HostResourceRequestState.ACTIVE:
            raise ResourceAdmissionError("RESOURCE_LEASE_NOT_ACTIVE")
        env = dict(base_environment or os.environ)
        env[LEASE_ENV] = lease_id
        return env

    def run_bounded_pytest(
        self,
        *,
        python_executable: str,
        pytest_args: Sequence[str],
        cwd: str | pathlib.Path,
        attempt_id: str,
        agent_instance: str,
        idempotency_key: Optional[str] = None,
        parent_lease_id: Optional[str] = None,
        timeout_seconds: float = 7200.0,
        heartbeat_interval_seconds: float = 30.0,
        base_environment: Optional[Mapping[str, str]] = None,
        force_heavy: bool = False,
    ) -> Dict[str, Any]:
        """Run only ``<python> -m pytest`` through the real subprocess path."""
        if not python_executable or isinstance(pytest_args, (str, bytes)) or not isinstance(pytest_args, Sequence):
            raise ValueError("python executable and pytest args are required")
        if timeout_seconds <= 0 or heartbeat_interval_seconds <= 0:
            raise ValueError("timeouts must be positive")
        executable = self._validate_python_executable(python_executable)
        cwd_path = pathlib.Path(cwd).expanduser().resolve()
        if not cwd_path.is_dir():
            raise ValueError("pytest cwd must be an existing directory")
        normalized_args = [str(arg) for arg in pytest_args]
        if normalized_args and normalized_args[0] == "--":
            normalized_args = normalized_args[1:]
        classification = classify_pytest_invocation(normalized_args, cwd=cwd_path)
        if force_heavy and classification == "pytest_focused":
            classification = "pytest_full"
        command = [str(executable), "-m", "pytest", *normalized_args]
        command_sha256 = hashlib.sha256(json.dumps(command, separators=(",", ":")).encode("utf-8")).hexdigest()
        if classification == "pytest_focused":
            admission = self._log_focused_request(
                attempt_id=attempt_id,
                agent_instance=agent_instance,
                idempotency_key=idempotency_key,
                command_sha256=command_sha256,
            )
        else:
            admission = self.request(
                purpose="pytest_full" if classification == "pytest_full" else "pytest_heavy",
                attempt_id=attempt_id,
                agent_instance=agent_instance,
                idempotency_key=idempotency_key,
                command_sha256=command_sha256,
                parent_lease_id=parent_lease_id,
                environment=base_environment,
            )
        if admission.get("idempotent_replay"):
            replay_state = admission["state"]
            replay_status = "ALREADY_ACTIVE" if replay_state in {
                HostResourceRequestState.ACTIVE.value,
                HostResourceRequestState.INHERITED.value,
            } else "QUEUED" if replay_state == HostResourceRequestState.QUEUED.value else "ALREADY_TERMINAL"
            return {**admission, "classification": classification, "status": replay_status, "exit_code": None}
        if admission["state"] == HostResourceRequestState.QUEUED.value:
            return {**admission, "classification": classification, "status": "QUEUED", "exit_code": None}

        request_id = admission["request_id"]
        lease_id = admission["lease_id"]
        env_source = dict(os.environ)
        if base_environment is not None:
            env_source.update({str(key): str(value) for key, value in base_environment.items()})
        env = {
            str(key): str(value)
            for key, value in env_source.items()
            if str(key) in _CHILD_ENV_ALLOWLIST or str(key).startswith("TDCONDUCTOR_")
        }
        env.pop(LEASE_ENV, None)
        if lease_id:
            env[LEASE_ENV] = lease_id
        started = time.monotonic()
        process: Optional[subprocess.Popen[str]] = None
        stdout = ""
        stderr = ""
        timed_out = False
        recovery_required = False
        try:
            process = subprocess.Popen(
                command,
                cwd=str(pathlib.Path(cwd).resolve()),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
            process_start_time: Optional[float]
            try:
                process_start_time = psutil.Process(process.pid).create_time()
            except (OSError, psutil.Error):
                process_start_time = None
            if admission["state"] == HostResourceRequestState.ACTIVE.value:
                with self.store._connection() as conn:
                    conn.execute(
                        "UPDATE host_resource_leases SET process_pid = ?, process_start_time = ? WHERE lease_id = ?",
                        (process.pid, process_start_time, lease_id),
                    )
            sequence = 1
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=heartbeat_interval_seconds)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= timeout_seconds:
                        timed_out = True
                        process.terminate()
                        try:
                            stdout, stderr = process.communicate(timeout=10)
                        except subprocess.TimeoutExpired:
                            # Try the retained handle once more. If the
                            # terminal state still cannot be observed, keep
                            # the lease recovery-required instead of releasing
                            # capacity while an unknown child may be alive.
                            try:
                                process.kill()
                                stdout, stderr = process.communicate(timeout=10)
                            except (OSError, subprocess.TimeoutExpired):
                                recovery_required = True
                                stdout, stderr = "", "child termination could not be observed"
                        break
                    if lease_id:
                        sequence += 1
                        self.heartbeat(lease_id, sequence)
            return {
                **admission,
                "classification": classification,
                "status": "TIMEOUT" if timed_out else ("PASSED" if process.returncode == 0 else "FAILED"),
                "exit_code": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        finally:
            # A failed Popen before a child exists is safe to release. Once a
            # child ran, release is still explicit and the retained handle above
            # has observed its terminal state.
            if recovery_required or (process is not None and process.poll() is None):
                self._mark_recovery(request_id, reason="PYTEST_TERMINATION_AMBIGUOUS")
            elif lease_id:
                self.release(request_id, reason="PYTEST_TIMEOUT" if timed_out else "PYTEST_COMPLETED")

    @staticmethod
    def _validate_python_executable(python_executable: str) -> pathlib.Path:
        candidate = pathlib.Path(python_executable).expanduser().resolve()
        if not candidate.is_file() or not _PYTHON_EXECUTABLE_RE.fullmatch(candidate.name):
            raise ValueError("pytest adapter requires an existing Python interpreter executable")
        return candidate

    def _log_focused_request(
        self,
        *,
        attempt_id: str,
        agent_instance: str,
        idempotency_key: Optional[str],
        command_sha256: str,
    ) -> Dict[str, Any]:
        idempotency_key = idempotency_key or f"resource_{uuid.uuid4().hex}"
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM host_resource_requests WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                return self._request_result(conn, self.store._row_to_resource_request(existing), replayed=True)
            now = current_utc_iso()
            request = HostResourceRequest(
                request_id=f"rr_{uuid.uuid4().hex[:12]}",
                idempotency_key=idempotency_key,
                resource_key=self.resource_key,
                purpose="pytest_focused",
                attempt_id=attempt_id,
                agent_instance=agent_instance,
                state=HostResourceRequestState.RELEASED,
                released_at_utc=now,
                command_sha256=command_sha256,
                reason_code="PYTEST_FOCUSED_NO_HEAVY_LEASE",
            )
            self._insert_request(conn, request)
            self._event(
                conn,
                request.request_id,
                None,
                None,
                request.state.value,
                "resource-adapter",
                request.reason_code or "PYTEST_FOCUSED_NO_HEAVY_LEASE",
            )
            return self._request_result(conn, request)

    @staticmethod
    def _validate_request(
        purpose: str, attempt_id: str, agent_instance: str, ttl: int, priority: int, resource_key: str = RESOURCE_KEY
    ) -> None:
        if purpose not in VALID_PURPOSES:
            raise ValueError(f"unsupported resource purpose: {purpose}")
        if not attempt_id or not agent_instance:
            raise ValueError("attempt_id and agent_instance are required")
        if ttl < 1:
            raise ValueError("lease TTL must be positive")
        if not 0 <= priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")

        # Cross-contamination invariants
        # A pytest or playwright purpose must NEVER admit into a cdp:* pool
        if (purpose.startswith("pytest_") or purpose == "playwright") and resource_key.startswith("cdp:"):
            raise ValueError(f"pytest purpose '{purpose}' cannot consume CDP pool '{resource_key}'")

        # A cdp_provider or cdp_* purpose must NEVER consume host:heavy
        if (purpose == "cdp_provider" or purpose.startswith("cdp_")) and resource_key == "host:heavy":
            raise ValueError(f"CDP purpose '{purpose}' cannot consume '{resource_key}'")

        # Specific purpose to pool alignment
        if purpose == "cdp_perplexity" and resource_key != "cdp:perplexity":
            raise ValueError(f"purpose '{purpose}' cannot consume pool '{resource_key}'")
        if purpose == "cdp_chatgpt" and resource_key != "cdp:chatgpt":
            raise ValueError(f"purpose '{purpose}' cannot consume pool '{resource_key}'")
        if purpose == "cdp_gemini" and resource_key != "cdp:gemini":
            raise ValueError(f"purpose '{purpose}' cannot consume pool '{resource_key}'")

    def _mark_recovery(self, request_id: str, *, reason: str) -> None:
        """Persist an ambiguous child outcome without releasing capacity."""
        with self.store._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state FROM host_resource_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if not row or row["state"] not in {
                HostResourceRequestState.ACTIVE.value,
                HostResourceRequestState.INHERITED.value,
            }:
                return
            previous_state = row["state"]
            conn.execute(
                "UPDATE host_resource_requests SET state = ?, reason_code = ? WHERE request_id = ?",
                (HostResourceRequestState.RECOVERY_REQUIRED.value, reason, request_id),
            )
            lease_row = conn.execute(
                "SELECT lease_id FROM host_resource_leases WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            self._event(
                conn,
                request_id,
                lease_row["lease_id"] if lease_row else None,
                previous_state,
                HostResourceRequestState.RECOVERY_REQUIRED.value,
                "resource-adapter",
                reason,
            )

    @staticmethod
    def _insert_request(conn: Any, request: HostResourceRequest) -> None:
        conn.execute(
            """
            INSERT INTO host_resource_requests (
                request_id, idempotency_key, resource_key, purpose, attempt_id,
                agent_instance, state, priority, parent_lease_id, command_sha256,
                created_at_utc, released_at_utc, reason_code, slot_key, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.idempotency_key,
                request.resource_key,
                request.purpose,
                request.attempt_id,
                request.agent_instance,
                request.state.value,
                request.priority,
                request.parent_lease_id,
                request.command_sha256,
                request.created_at_utc,
                request.released_at_utc,
                request.reason_code,
                request.slot_key,
                request.schema_version,
            ),
        )

    @staticmethod
    def _create_lease_locked(conn: Any, request: HostResourceRequest, *, lease_ttl_seconds: int, now: datetime) -> str:
        lease_id = f"hrl_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO host_resource_leases (
                lease_id, request_id, resource_key, attempt_id, agent_instance,
                heartbeat_sequence, expires_at_utc, last_heartbeat_utc,
                process_pid, process_start_time, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lease_id,
                request.request_id,
                request.resource_key,
                request.attempt_id,
                request.agent_instance,
                1,
                _iso(now + timedelta(seconds=lease_ttl_seconds)),
                _iso(now),
                None,
                None,
                "conductor.resource-lease.v1",
            ),
        )
        return lease_id

    def _promote_locked(
        self, conn: Any, *, resource_key: Optional[str] = None, actor: str
    ) -> Optional[Dict[str, Any]]:
        target_resource_key = resource_key or self.resource_key
        pool = conn.execute(
            "SELECT * FROM host_resource_pools WHERE resource_key = ?", (target_resource_key,)
        ).fetchone()
        if not pool or not bool(pool["enabled"]):
            return None
        capacity = int(pool["capacity"])
        if capacity < 1:
            return None

        active_rows = conn.execute(
            """
            SELECT state, slot_key FROM host_resource_requests
            WHERE resource_key = ? AND state IN (?, ?)
            """,
            (target_resource_key, HostResourceRequestState.ACTIVE.value, HostResourceRequestState.RECOVERY_REQUIRED.value),
        ).fetchall()
        if len(active_rows) >= capacity:
            return None

        active_slot_keys = {
            row["slot_key"] for row in active_rows
            if row["slot_key"]
        }

        queued_rows = conn.execute(
            """
            SELECT * FROM host_resource_requests
            WHERE resource_key = ? AND state = ?
            ORDER BY priority DESC, created_at_utc, request_id
            """,
            (target_resource_key, HostResourceRequestState.QUEUED.value),
        ).fetchall()

        eligible_row = None
        for qrow in queued_rows:
            req_slot = qrow["slot_key"] if "slot_key" in qrow.keys() and qrow["slot_key"] else ""
            if req_slot and req_slot in active_slot_keys:
                # Documented choice: When the head of the queue is blocked only by slot exclusivity,
                # promotion skips it and takes the next eligible request (non-strict FIFO for slot exclusivity).
                continue
            eligible_row = qrow
            break

        if eligible_row is None:
            return None

        request = self.store._row_to_resource_request(eligible_row)
        now = _now()
        conn.execute(
            "UPDATE host_resource_requests SET state = ?, reason_code = ? WHERE request_id = ?",
            (HostResourceRequestState.ACTIVE.value, "HOST_RESOURCE_PROMOTED", request.request_id),
        )
        lease_id = self._create_lease_locked(conn, request, lease_ttl_seconds=DEFAULT_LEASE_TTL_SECONDS, now=now)
        self._event(conn, request.request_id, lease_id, request.state.value, HostResourceRequestState.ACTIVE.value, actor, "HOST_RESOURCE_PROMOTED")
        return {"request_id": request.request_id, "lease_id": lease_id, "state": HostResourceRequestState.ACTIVE.value}

    @staticmethod
    def _event(
        conn: Any,
        request_id: str,
        lease_id: Optional[str],
        previous: Optional[str],
        next_state: str,
        actor: str,
        reason: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO host_resource_events (
                event_id, request_id, lease_id, previous_state, next_state,
                actor_identity, reason_code, recorded_at_utc, details_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"hre_{uuid.uuid4().hex[:12]}",
                request_id,
                lease_id,
                previous,
                next_state,
                actor,
                reason,
                current_utc_iso(),
                json.dumps(dict(details or {}), sort_keys=True),
                "conductor.resource-event.v1",
            ),
        )

    @staticmethod
    def _request_result(
        conn: Any,
        request: HostResourceRequest,
        lease_id: Optional[str] = None,
        replayed: bool = False,
    ) -> Dict[str, Any]:
        if lease_id is None:
            row = conn.execute(
                "SELECT lease_id FROM host_resource_leases WHERE request_id = ?", (request.request_id,)
            ).fetchone()
            lease_id = row["lease_id"] if row else None
        return {
            "request_id": request.request_id,
            "resource_key": request.resource_key,
            "purpose": request.purpose,
            "state": request.state.value,
            "lease_id": lease_id,
            "parent_lease_id": request.parent_lease_id,
            "reason_code": request.reason_code,
            "slot_key": request.slot_key,
            "priority": request.priority,
            "idempotent_replay": replayed,
        }
