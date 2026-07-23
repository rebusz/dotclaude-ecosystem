# TruthDeck

TruthDeck compiles current evidence into an immutable `truthdeck.snapshot.v1` JSON artifact. It reports six independent stages—planned, implemented, exact-head reviewed, CI, merged, and runtime proven—and selects one advisory next action. It never repairs state, starts applications, or touches broker/order paths.

## First snapshot

```powershell
python scripts/truthdeck_install.py install
python scripts/truthctl.py validate-registry
python scripts/truthctl.py snapshot --repo . --plan design/plans/<plan>.md
```

Use `--no-store` only for tests. The default append-only store is `~/.truthdeck/snapshots/`; `latest.json` is a digest-checked pointer, not the snapshot itself.

Add `--pr N`, `--review-packet PATH`, and `--review-result PATH` only when those explicit sources are in scope. `--require planned,implemented` controls readiness without hiding the other reported stages.

Registry `task_aliases` can bind a name to absolute repo/plan paths (and, optionally, an exact handoff path plus SHA-256). Use `snapshot --task NAME` or `verify-handoff --task NAME`; aliases cannot be mixed with explicit scope arguments.

Verify a handoff with both integrity and live Git reference checks:

```powershell
python scripts/truthctl.py verify-handoff --path <handoff.md> --sha256 <expected> --repo <repo>
```

## States and exit codes

- `PASS` / `NOT_APPLICABLE`: 0
- invalid input or registry: 2
- boundary refusal: 3
- `HOLD`: 10
- `BLOCKED`: 11
- `UNKNOWN`: 12
- total collection deadline: 124

Stored snapshots are re-evaluated for freshness by `next` and `diff`; the sealed JSON is never overwritten.

## Runtime profiles

Runtime execution is possible only through code-owned probe IDs. TSU v1 includes two local read-only JSON probes. Tsignal v1 intentionally has no runtime probe because the inspected candidate writes report files; its runtime gate therefore remains unavailable until a separately reviewed, stdout-only readback exists.

## Optional MCP

Install `requirements-truthdeck-mcp.txt`, then activate with `truthdeck_install.py install --enable-mcp codex`, `claude`, or `both`. The stdio server exposes exactly four tools: snapshot, next, verify handoff, and diff. Installer edits are marker/ownership checked and backed up.

For an explicit self-readback, add `--installation-home <home>` to `snapshot`. This emits separate facts for CLI installation, Codex/Claude skill discovery, and each host's MCP registration; these facts do not change lifecycle gates.

## Rollback

`python scripts/truthdeck_install.py uninstall` removes only manifest-owned files whose hashes still match and owned MCP entries. It preserves the registry and all snapshots. Drift causes a fail-closed `HOLD`.
