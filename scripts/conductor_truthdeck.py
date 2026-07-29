"""TruthDeck integration and read-only checkpoint seam for TruthDeck Conductor.

Consumes shipped session_state.py and truthctl snapshots via a read-only seam without writing session_registry.json.
Distinguishes valid snapshots with non-green gates (exit 12) from true collector failures (Decision D4).
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any, Dict, Optional, Tuple, Union



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
