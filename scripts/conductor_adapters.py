"""Host capability registry, host classification matrices, and host doctor probes for TruthDeck Conductor.

Maintains host classifications (PROVEN, HOLD_NOT_INSTALLED, HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT, HOLD).
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import os
import pathlib
import shutil
from typing import Any, Dict


class HostClassification:
    PROVEN = "PROVEN"
    HOLD_NOT_INSTALLED = "HOLD_NOT_INSTALLED"
    HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT = "HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT"
    HOLD_UNSUPPORTED = "HOLD_UNSUPPORTED"


HOST_CAPABILITY_MATRIX: Dict[str, Dict[str, str]] = {
    "claude_code": {
        "cooperative_client": HostClassification.PROVEN,
        "session_event_lifecycle": HostClassification.PROVEN,
        "autonomous_dispatch": HostClassification.PROVEN,
        "executable": "claude",
    },
    "kimi_cli": {
        "cooperative_client": HostClassification.PROVEN,
        "session_event_lifecycle": HostClassification.PROVEN,
        "autonomous_dispatch": HostClassification.PROVEN,
        "executable": "kimi",
    },
    "codex": {
        "cooperative_client": HostClassification.PROVEN,
        "session_event_lifecycle": HostClassification.HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT,
        "autonomous_dispatch": HostClassification.HOLD_UNSUPPORTED,
        "executable": "codex",
    },
    "cursor": {
        "cooperative_client": HostClassification.PROVEN,
        "session_event_lifecycle": HostClassification.PROVEN,
        "autonomous_dispatch": HostClassification.HOLD_UNSUPPORTED,
        "executable": "cursor",
    },
    "antigravity_ide": {
        "cooperative_client": HostClassification.PROVEN,
        "session_event_lifecycle": HostClassification.HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT,
        "autonomous_dispatch": HostClassification.HOLD_UNSUPPORTED,
        "executable": "antigravity-ide",
    },
    "agy_cli": {
        "cooperative_client": HostClassification.HOLD_NOT_INSTALLED,
        "session_event_lifecycle": HostClassification.HOLD_NOT_INSTALLED,
        "autonomous_dispatch": HostClassification.HOLD_NOT_INSTALLED,
        "executable": "agy",
    },
}


class ConductorHostRegistry:
    """Registry probing host installation status and advertising capability matrix."""

    @staticmethod
    def probe_host(host_key: str) -> Dict[str, Any]:
        """Probe installed state and capabilities of a host."""
        spec = HOST_CAPABILITY_MATRIX.get(host_key)
        if not spec:
            return {"host_key": host_key, "installed": False, "classification": HostClassification.HOLD_UNSUPPORTED}

        exe_name = spec["executable"]
        exe_path = shutil.which(exe_name)

        if not exe_path:
            # Special case for Antigravity IDE known Windows installation path
            if host_key == "antigravity_ide":
                win_path = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity IDE" / "bin" / "antigravity-ide.cmd"
                if win_path.exists():
                    exe_path = str(win_path)

        installed = exe_path is not None

        return {
            "host_key": host_key,
            "installed": installed,
            "executable_path": exe_path,
            "cooperative_client": spec["cooperative_client"] if installed else HostClassification.HOLD_NOT_INSTALLED,
            "session_event_lifecycle": spec["session_event_lifecycle"] if installed else HostClassification.HOLD_NOT_INSTALLED,
            "autonomous_dispatch": spec["autonomous_dispatch"] if installed else HostClassification.HOLD_NOT_INSTALLED,
        }

    @classmethod
    def doctor_report(cls) -> Dict[str, Any]:
        """Generate host doctor diagnostics for all known host keys."""
        report = {}
        for key in HOST_CAPABILITY_MATRIX.keys():
            report[key] = cls.probe_host(key)
        return report
