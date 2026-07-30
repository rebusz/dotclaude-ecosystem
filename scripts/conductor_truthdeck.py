"""TruthDeck integration and read-only checkpoint seam for TruthDeck Conductor.

Consumes shipped session_state.py and truthctl snapshots via a read-only seam without writing session_registry.json.
Distinguishes valid snapshots with non-green gates (exit 12) from true collector failures (Decision D4).
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple, Union


MIN_TRUTHCTL_VERSION = (1, 0, 0)


def check_truthctl_version(executable: str = "truthctl") -> Dict[str, Any]:
    """Return a fail-closed version check for the installed TruthDeck CLI."""
    resolved = shutil.which(executable)
    if not resolved:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "version": None,
            "required_minimum": ".".join(str(part) for part in MIN_TRUTHCTL_VERSION),
            "error": "truthctl executable not found",
        }
    try:
        result = subprocess.run(
            [resolved, "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "version": None,
            "required_minimum": ".".join(str(part) for part in MIN_TRUTHCTL_VERSION),
            "error": str(err),
        }

    version_text = (result.stdout or result.stderr or "").strip()
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", version_text)
    version = tuple(int(part) for part in match.groups()) if match else None
    minimum = ".".join(str(part) for part in MIN_TRUTHCTL_VERSION)
    if result.returncode != 0 or version is None:
        return {
            "ok": False,
            "status": "UNKNOWN",
            "version": version_text or None,
            "required_minimum": minimum,
            "error": f"truthctl version probe failed with exit code {result.returncode}",
        }
    if version < MIN_TRUTHCTL_VERSION:
        return {
            "ok": False,
            "status": "BLOCKED",
            "version": ".".join(str(part) for part in version),
            "required_minimum": minimum,
            "error": "truthctl version is below the pinned minimum",
        }
    return {
        "ok": True,
        "status": "PASS",
        "version": ".".join(str(part) for part in version),
        "required_minimum": minimum,
    }


class ConductorTruthDeckSeam:
    """Read-only evidence checkpoint runner calling truthctl or session_state."""

    def __init__(self, repo_root: Union[str, pathlib.Path]):
        self.repo_root = pathlib.Path(repo_root).expanduser().resolve()

    def run_checkpoint_snapshot(self, boundary: str, plan_path: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
        """Run truthctl snapshot --no-store --json.

        Returns (gate_status, snapshot_json).
        Decision D4: exit code 12 with parseable JSON is a VALID snapshot with non-green gates.
        """
        cmd = ["truthctl", "snapshot", "--repo", str(self.repo_root), "--no-store", "--json"]
        if plan_path:
            cmd.extend(["--plan", plan_path])

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            # Process JSON output
            stdout_text = res.stdout.strip()
            if not stdout_text:
                return "UNKNOWN", {"error": "truthctl produced empty output", "exit_code": res.returncode}

            snapshot_data = json.loads(stdout_text)
            gate_status = snapshot_data.get("overall_status", "UNKNOWN")

            # Exit code 12 or 0 are valid snapshots per D4
            if res.returncode in {0, 12}:
                return gate_status, snapshot_data
            else:
                return "UNKNOWN", {"error": f"truthctl failed with exit code {res.returncode}", "raw": stdout_text}

        except Exception as err:
            return "UNKNOWN", {"error": str(err)}
