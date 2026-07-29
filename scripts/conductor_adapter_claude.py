"""Claude Code host adapter for TruthDeck Conductor.

Dispatches non-interactive execution via `claude -p prompt`.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any, Dict, Union


class ClaudeCodeAdapter:
    """Claude Code CLI non-interactive adapter."""

    @staticmethod
    def is_available() -> bool:
        return subprocess.run(["claude", "--version"], capture_output=True, text=True, check=False).returncode == 0

    @staticmethod
    def dispatch_noninteractive(prompt: str, cwd: Union[str, pathlib.Path], timeout_seconds: int = 7200) -> Dict[str, Any]:
        """Dispatch non-interactive Claude Code process."""
        cmd = ["claude", "-p", prompt]
        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "success": res.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "error": f"Claude Code timed out after {timeout_seconds}s", "success": False}
        except Exception as err:
            return {"exit_code": -1, "error": str(err), "success": False}
