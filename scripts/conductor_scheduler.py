"""Deterministic scheduler engine for TruthDeck Conductor.

Orders eligible WorkItems by priority, dependencies, authority, risk class, and aging.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from scripts.conductor_model import WorkItem, WorkItemState
from scripts.conductor_store import ConductorStore


class ConductorScheduler:
    """Deterministic scheduler for WorkItems."""

    def __init__(self, store: ConductorStore):
        self.store = store

    def get_eligible_work_items(self) -> List[WorkItem]:
        """Return all WorkItems in READY state whose dependencies are completed."""
        ready_items = self.store.list_work_items(state=WorkItemState.READY)
        completed_items = {w.work_item_id for w in self.store.list_work_items(state=WorkItemState.COMPLETED)}

        eligible = []
        for item in ready_items:
            # Check hard dependencies
            deps_satisfied = all(dep_id in completed_items for dep_id in item.dependency_ids)
            if deps_satisfied:
                eligible.append(item)

        return eligible

    def select_next_work_item(self, repo_id: Optional[str] = None) -> Tuple[Optional[WorkItem], List[Dict[str, Any]]]:
        """Deterministically select next WorkItem to execute.

        Returns (selected_item, rejected_candidates_with_reasons).
        """
        all_ready = self.store.list_work_items(state=WorkItemState.READY)
        all_completed = {w.work_item_id for w in self.store.list_work_items(state=WorkItemState.COMPLETED)}

        if repo_id:
            all_ready = [w for w in all_ready if w.repo_id == repo_id]

        eligible: List[WorkItem] = []
        rejected: List[Dict[str, Any]] = []

        for item in all_ready:
            # Check dependency satisfaction
            unsatisfied = [dep for dep in item.dependency_ids if dep not in all_completed]
            if unsatisfied:
                rejected.append({
                    "work_item_id": item.work_item_id,
                    "title": item.title,
                    "reason_code": "DEPENDENCY_UNSATISFIED",
                    "unsatisfied_dependencies": unsatisfied,
                })
                continue

            # Check R2/R3 operator authorization
            if item.risk_class in {"R2", "R3"}:
                auth = self.store.get_authorization(item.work_item_id)
                if not auth or not auth.interactive_provenance_proven:
                    rejected.append({
                        "work_item_id": item.work_item_id,
                        "title": item.title,
                        "reason_code": "AUTHORIZATION_MISSING",
                    })
                    continue

            eligible.append(item)

        if not eligible:
            return None, rejected

        # Deterministic sorting key:
        # 1. Priority (descending)
        # 2. Risk class weight (R3 > R2 > R1 > R0)
        # 3. Created time (ascending / aging)
        # 4. WorkItem ID (ascending tie-breaker)
        risk_weight = {"R3": 4, "R2": 3, "R1": 2, "R0": 1}

        def sort_key(item: WorkItem) -> Tuple[int, int, str, str]:
            w = risk_weight.get(item.risk_class, 1)
            return (-item.priority, -w, item.created_at_utc, item.work_item_id)

        eligible.sort(key=sort_key)
        selected = eligible[0]

        for item in eligible[1:]:
            rejected.append({
                "work_item_id": item.work_item_id,
                "title": item.title,
                "reason_code": "LOWER_SCHEDULER_PRIORITY",
            })

        return selected, rejected
