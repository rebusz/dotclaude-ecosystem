# Workflow OS B0 Capture Contract

Date: 2026-06-29
Risk: R1, measurement-only
Scope: `dotclaude-ecosystem` tooling only. No TSU/Tsignal runtime, broker, order-path, or trading-config writes.

## Why

`headroom-rtk-benchmark` must stay deferred until a real mixed-session B0 baseline exists at:

```text
design/baselines/workflow_os_b0_mixed_sessions.json
```

The A1 kernel baseline is not enough for proxy evaluation because the plan requires total-cost measurement across representative sessions, plus a no-regression quality gate.

## What Landed

`scripts/session_cost_probe.py` now has a fail-closed `mixed-baseline` command. It accepts exactly three measured session JSON files, one per required session class:

- `read_heavy_audit`
- `multi_file_edit`
- `research_plan`

Each session JSON must include real Claude Code or equivalent runtime numbers:

- `input_tokens`
- `output_tokens`
- `cache_read_input_tokens`
- `cost_usd`
- `startup_context_tokens`
- optional `cache_creation_input_tokens`

Each session JSON must also include a `quality_baseline` with:

- `summary`
- non-empty `validation_commands`
- optional `expected_artifacts`

## Session JSON Shape

```json
{
  "id": "read_heavy_audit",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cost_usd": 0.0,
    "startup_context_tokens": 0
  },
  "quality_baseline": {
    "summary": "Describe the artifact/functionality produced by this baseline session.",
    "validation_commands": ["python -m pytest scripts/tests"],
    "expected_artifacts": ["path/to/changed-or-reviewed-artifact.md"]
  }
}
```

Do not commit placeholder session inputs. Use only measured values from real representative sessions.

## Generate The Real B0 Baseline

```powershell
python scripts/session_cost_probe.py mixed-baseline `
  --output design/baselines/workflow_os_b0_mixed_sessions.json `
  --session-json path/to/read_heavy_audit.json `
  --session-json path/to/multi_file_edit.json `
  --session-json path/to/research_plan.json
```

When that file exists and passes review, the existing workflow trigger can surface the Headroom/RTK benchmark slice.

## Validation

Latest local validation after adding the contract:

```text
python -m pytest scripts\tests
50 passed
```

## Boundaries

- This does not install or run Headroom/RTK.
- This does not create `workflow_os_b0_mixed_sessions.json`.
- This does not change any agent runtime defaults.
- This does not touch income repos or trading paths.
