"""Claude Code host adapter for TruthDeck Conductor.

Dispatches non-interactive execution via `claude -p prompt`.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import pathlib
import os
import uuid
import subprocess
from typing import Any, Dict, Union


class ClaudeCodeAdapter:
    """Claude Code CLI non-interactive adapter."""

    @staticmethod
    def is_available() -> bool:
        try:
            from scripts.conductor_resources import HostResourceManager
            from scripts.conductor_store import ConductorStore

            lane_id = f"agent_probe_{uuid.uuid4().hex}"
            result = HostResourceManager(ConductorStore()).run_bounded_command(
                ["claude", "--version"], cwd=pathlib.Path.cwd(), lane_id=lane_id,
                owner_id=os.environ.get("CONDUCTOR_OWNER_ID") or lane_id, timeout_seconds=10,
                memory_budget_gib=0.1,
            )
            return result["status"] == "PASSED" and result["exit_code"] == 0
        except Exception:
            return False

    @staticmethod
    def dispatch_noninteractive(prompt: str, cwd: Union[str, pathlib.Path], timeout_seconds: int = 7200,
                                *, owner_id: str | None = None, lane_id: str | None = None) -> Dict[str, Any]:
        """Dispatch non-interactive Claude Code process."""
        cmd = ["claude", "-p", prompt]
        try:
            from scripts.conductor_resources import HostResourceManager
            from scripts.conductor_store import ConductorStore

            lane_id = lane_id or f"agent_{uuid.uuid4().hex}"
            result = HostResourceManager(ConductorStore()).run_bounded_command(
                cmd, cwd=cwd, lane_id=lane_id,
                owner_id=owner_id or os.environ.get("CONDUCTOR_OWNER_ID") or lane_id,
                timeout_seconds=timeout_seconds,
            )
            return {**result, "success": result["status"] == "PASSED"}
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "error": f"Claude Code timed out after {timeout_seconds}s", "success": False}
        except Exception as err:
            return {"exit_code": -1, "error": str(err), "success": False}
