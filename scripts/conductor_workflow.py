"""Workflow bridge mapping WorkItems to existing /fwf or /fwp entry contracts.

Preserves existing workflow ownership without reproducing workflow stages inside Conductor.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations


from scripts.conductor_model import WorkItem


class ConductorWorkflowBridge:
    """Workflow entry contract mapping."""

    @staticmethod
    def get_workflow_command(item: WorkItem) -> str:
        """Return canonical /fwf or /fwp invocation command for WorkItem."""
        workflow_cmd = f"/{item.workflow}"
        plan_arg = item.plan_path if item.plan_path else ""
        return f"{workflow_cmd} {item.repo_path}/{plan_arg}".strip()

    @staticmethod
    def validate_workflow_contract(item: WorkItem) -> bool:
        """Validate workflow parameters."""
        if item.workflow not in {"fwf", "fwp"}:
            return False
        if item.risk_class not in {"R0", "R1", "R2", "R3"}:
            return False
        return True
