"""Static 6-tool MCP server for TruthDeck Conductor.

Exposes conductor_status, conductor_get_work_item, conductor_claim, conductor_heartbeat, conductor_checkpoint, conductor_report over the standard store/commands core.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import pathlib
import sys
import uuid
from typing import Any, Dict

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_commands import ConductorCommandProcessor  # noqa: E402
from scripts.conductor_model import CommandEnvelope  # noqa: E402
from scripts.conductor_store import ConductorStore  # noqa: E402


def handle_mcp_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an MCP tool call against ConductorStore."""
    store = ConductorStore()
    processor = ConductorCommandProcessor(store=store)

    if tool_name == "conductor_status":
        envelope = CommandEnvelope(
            command_id=f"mcp_stat_{uuid.uuid4().hex[:8]}",
            command_type="status",
            payload={},
            idempotency_key=f"mcp_stat_idemp_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        return receipt.result

    elif tool_name == "conductor_get_work_item":
        work_item_id = arguments["work_item_id"]
        item = store.get_work_item(work_item_id)
        return item.to_dict() if item else {"error": f"WorkItem {work_item_id} not found"}

    elif tool_name == "conductor_claim":
        envelope = CommandEnvelope(
            command_id=f"mcp_claim_{uuid.uuid4().hex[:8]}",
            command_type="claim",
            payload=arguments,
            idempotency_key=f"mcp_claim_idemp_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        return receipt.to_dict()

    elif tool_name == "conductor_heartbeat":
        envelope = CommandEnvelope(
            command_id=f"mcp_hb_{uuid.uuid4().hex[:8]}",
            command_type="heartbeat",
            payload=arguments,
            idempotency_key=f"mcp_hb_idemp_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        return receipt.to_dict()

    elif tool_name == "conductor_checkpoint":
        envelope = CommandEnvelope(
            command_id=f"mcp_chk_{uuid.uuid4().hex[:8]}",
            command_type="checkpoint",
            payload=arguments,
            idempotency_key=f"mcp_chk_idemp_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        return receipt.to_dict()

    elif tool_name == "conductor_report":
        envelope = CommandEnvelope(
            command_id=f"mcp_rep_{uuid.uuid4().hex[:8]}",
            command_type="complete" if arguments.get("status") == "COMPLETED" else "block",
            payload=arguments,
            idempotency_key=f"mcp_rep_idemp_{uuid.uuid4().hex[:8]}",
        )
        receipt = processor.process_envelope(envelope)
        return receipt.to_dict()

    else:
        return {"error": f"Unknown MCP tool: {tool_name}"}


if __name__ == "__main__":
    print("TruthDeck Conductor MCP Server helper loaded.")
