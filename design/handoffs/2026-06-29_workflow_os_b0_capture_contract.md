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

## Claude JSONL Extraction Path

Claude Code stores per-message usage records in project JSONL files. `session_cost_probe.py` can now extract token/cache/output counts from those logs without reading prompt text into the output.

List candidate sessions by token volume:

```powershell
python scripts/session_cost_probe.py jsonl-inventory `
  --dir "$env:USERPROFILE\.claude\projects\D--APPS-TSU" `
  --limit 12
```

Inspect one candidate session:

```powershell
python scripts/session_cost_probe.py jsonl-summary `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\<session>.jsonl"
```

Build one B0 session JSON from real JSONL usage plus explicit `/cost`:

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\<session>.jsonl" `
  --output path/to/read_heavy_audit.json `
  --session-id read_heavy_audit `
  --cost-usd <value-from-claude-cost-readback> `
  --startup-context-tokens <fresh-context-probe-value> `
  --quality-summary "Describe the baseline artifact shape." `
  --validation-command "python -m pytest scripts/tests"
```

The extractor intentionally does not estimate model prices. If `/cost` is unavailable, the B0 baseline remains incomplete.

Observed local evidence: `C:\Users\dszub\.claude\projects\D--APPS-TSU\e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl` contains 370 assistant usage records with token/cache/output counters. This proves the usage side is recoverable; it does not prove `cost_usd`.

Candidate inventory for the local TSU JSONL corpus lives at `design/handoffs/2026-06-29_workflow_os_b0_candidate_inventory.md`. It is intentionally not a baseline and does not choose the three B0 session classes.

## Validation

Latest local validation after adding the contract and JSONL extractor:

```text
python -m pytest scripts\tests
58 passed
```

## Boundaries

- This does not install or run Headroom/RTK.
- This does not create `workflow_os_b0_mixed_sessions.json`.
- This does not change any agent runtime defaults.
- This does not touch income repos or trading paths.
