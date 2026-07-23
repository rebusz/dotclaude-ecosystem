"""Optional stdio-only MCP adapter exposing exactly four TruthDeck tools."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from truthctl import build_snapshot, re_evaluate
from truthdeck_handoff import verify_handoff
from truthdeck_model import Stage, snapshot_to_dict, utc_now
from truthdeck_render import render_diff
from truthdeck_storage import read_snapshot


def create_server() -> FastMCP:
    server = FastMCP("truthdeck")

    @server.tool()
    def truthdeck_snapshot(repos: list[str], registry: str, plan: str | None = None,
                           pr: int | None = None, profile: str | None = None,
                           require: str | None = None, review_packet: str | None = None,
                           review_result: str | None = None, artifacts: list[str] | None = None) -> dict:
        """Collect a read-only evidence snapshot without persisting it."""
        stages = tuple(Stage(item) for item in require.split(",")) if require else None
        snapshot = build_snapshot(
            repos=[Path(repo) for repo in repos], registry_path=Path(registry),
            plan=Path(plan) if plan else None, pr=pr, profile_name=profile, require=stages,
            review_packet=Path(review_packet) if review_packet else None,
            review_result=Path(review_result) if review_result else None,
            artifacts=tuple(Path(item) for item in (artifacts or ())),
        )
        return snapshot_to_dict(snapshot)

    @server.tool()
    def truthdeck_next(snapshot: str) -> dict:
        """Re-evaluate freshness and return one advisory next action."""
        current = re_evaluate(read_snapshot(Path(snapshot)))
        return dataclasses.asdict(current.next_action)

    @server.tool()
    def truthdeck_verify_handoff(path: str, sha256: str, repo: str | None = None,
                                 base_ref: str = "origin/main") -> dict:
        """Verify a handoff digest; its prose remains inert."""
        fact, details = verify_handoff(Path(path), sha256, observed_at_utc=utc_now(),
                                       repo=Path(repo) if repo else None, base_ref=base_ref)
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
