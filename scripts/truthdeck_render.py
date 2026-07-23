"""Bounded human rendering for TruthDeck snapshots and diffs."""

from __future__ import annotations

from truthdeck_model import Snapshot, snapshot_to_dict

MAX_MARKDOWN = 4000


def render_snapshot(snapshot: Snapshot, *, artifact_path: str | None = None, digest: str | None = None) -> str:
    lines = ["# TruthDeck", "", f"Snapshot: `{snapshot.snapshot_id}`", f"Observed: `{snapshot.observed_at_utc}`", "", "## Gates", ""]
    for gate in snapshot.gates:
        repo = f" ({gate.repo_id})" if gate.repo_id else ""
        reasons = ", ".join(r.value for r in gate.reason_codes) or "none"
        lines.append(f"- `{gate.stage.value}`{repo}: **{gate.state.value}** — {reasons}")
    lines.extend(["", "## Next action", "", snapshot.next_action.summary])
    if snapshot.conflicts:
        lines.extend(["", "## Conflicts", "", *[f"- {x}" for x in snapshot.conflicts]])
    if snapshot.boundaries:
        lines.extend(["", "## Boundaries", "", *[f"- {x}" for x in snapshot.boundaries]])
    if artifact_path:
        lines.extend(["", f"Artifact: `{artifact_path}`"])
    if digest:
        lines.append(f"SHA-256: `{digest}`")
    return _bounded("\n".join(lines))


def render_diff(before: Snapshot, after: Snapshot) -> str:
    left, right = snapshot_to_dict(before), snapshot_to_dict(after)
    left_facts = {(f.get("repo_id"), f["key"]): (f["state"], f.get("value")) for f in left["facts"]}
    right_facts = {(f.get("repo_id"), f["key"]): (f["state"], f.get("value")) for f in right["facts"]}
    left_gates = {(g.get("repo_id"), g["stage"]): (g["state"], tuple(g["reason_codes"])) for g in left["gates"]}
    right_gates = {(g.get("repo_id"), g["stage"]): (g["state"], tuple(g["reason_codes"])) for g in right["gates"]}
    lines = ["# TruthDeck diff", "", f"`{before.snapshot_id}` → `{after.snapshot_id}`", "", "## Changes", ""]
    for label, old, new in (("fact", left_facts, right_facts), ("gate", left_gates, right_gates)):
        for key in sorted(set(old) | set(new), key=str):
            if old.get(key) != new.get(key):
                lines.append(f"- {label} `{key}`: `{old.get(key)}` → `{new.get(key)}`")
    if len(lines) == 6:
        lines.append("- none")
    return _bounded("\n".join(lines))


def _bounded(value: str) -> str:
    if len(value) <= MAX_MARKDOWN:
        return value
    return value[: MAX_MARKDOWN - 25] + "\n… output truncated …\n"
