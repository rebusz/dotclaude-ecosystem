"""Optional stdio-only MCP adapter exposing exactly four TruthDeck tools."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from truthctl import build_snapshot, re_evaluate
from truthdeck_handoff import verify_handoff
from truthdeck_model import snapshot_to_dict, utc_now
from truthdeck_render import render_diff
from truthdeck_storage import read_snapshot


def create_server() -> FastMCP:
    server = FastMCP("truthdeck")

    @server.tool()
    def truthdeck_snapshot(repo: str, registry: str, plan: str | None = None,
                           pr: int | None = None, profile: str | None = None) -> dict:
        """Collect a read-only evidence snapshot without persisting it."""
        snapshot = build_snapshot(repos=[Path(repo)], registry_path=Path(registry),
                                  plan=Path(plan) if plan else None, pr=pr, profile_name=profile)
        return snapshot_to_dict(snapshot)

    @server.tool()
    def truthdeck_next(snapshot: str) -> dict:
        """Re-evaluate freshness and return one advisory next action."""
        current = re_evaluate(read_snapshot(Path(snapshot)))
        return dataclasses.asdict(current.next_action)

    @server.tool()
    def truthdeck_verify_handoff(path: str, sha256: str) -> dict:
        """Verify a handoff digest; its prose remains inert."""
        fact, details = verify_handoff(Path(path), sha256, observed_at_utc=utc_now())
        return {"fact": dataclasses.asdict(fact), **details}

    @server.tool()
    def truthdeck_diff(before: str, after: str) -> dict:
        """Compare two immutable snapshots after freshness re-evaluation."""
        left, right = re_evaluate(read_snapshot(Path(before))), re_evaluate(read_snapshot(Path(after)))
        return {"before": snapshot_to_dict(left), "after": snapshot_to_dict(right), "markdown": render_diff(left, right)}

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
