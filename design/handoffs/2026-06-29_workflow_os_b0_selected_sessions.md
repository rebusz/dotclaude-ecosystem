# Workflow OS B0 Selected Session Candidates

Date: 2026-06-29
Risk: R1 measurement prep
Status: mixed baseline generated

## Purpose

This packet narrows the B0 baseline gate from "choose three sessions" to three selected local TSU-adjacent Claude JSONL candidates. It does not create `design/baselines/workflow_os_b0_mixed_sessions.json` and does not estimate prices from token counts.

Machine-readable selection:

```text
design/baselines/b0_sessions/2026-06-29_selected_candidates.json
```

Cost and startup-context evidence:

```text
design/baselines/b0_sessions/2026-06-29_selected_cost_readbacks.json
```

Generated baseline:

```text
design/baselines/workflow_os_b0_mixed_sessions.json
```

## Selected Candidates

| B0 class | JSONL file | Cost readback | Startup context tokens | Why this one |
| --- | --- | --- | --- | --- |
| `read_heavy_audit` | `f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl` | `$36.78 sess` | `48871` | Read/Grep/Glob/PowerShell-heavy TSU/EcosystemControl audit shape with minimal edits. |
| `multi_file_edit` | `5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl` | `$69.18 sess` | `45615` | Edit-heavy workflow touching shared fusion/audit plan/tooling files. |
| `research_plan` | `e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl` | `$154.78 sess` | `44565` | Architecture/research planning session with Workflow/Agent use and TSU/Tsignal plan artifacts. |

The larger `a2789764-b080-4b74-be74-bb17db55652e.jsonl` was not selected because its metadata shows substantial WatchF work, so it is weaker as a TSU B0 representative despite the largest token total.

## Readback Method

The exact cost values were recovered from local Claude JSONL Stop hook footer lines containing cumulative `$... sess` values. For each selected session, the final and maximum observed cumulative value match:

- `read_heavy_audit`: 20 readbacks, max/last `$36.78 sess`
- `multi_file_edit`: 32 readbacks, max/last `$69.18 sess`
- `research_plan`: 62 readbacks, max/last `$154.78 sess`

These are readbacks from the runtime footer, not token-price estimates.

## Startup Context Method

The operator confirmed use of each selected session's first assistant context footprint as `startup_context_tokens`.

## Build Commands Used

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl" `
  --output design/baselines/b0_sessions/read_heavy_audit.json `
  --session-id read_heavy_audit `
  --cost-usd 36.78 `
  --startup-context-tokens 48871 `
  --quality-summary "Read-heavy audit artifact shape preserved" `
  --validation-command "python -m pytest scripts/tests"
```

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl" `
  --output design/baselines/b0_sessions/multi_file_edit.json `
  --session-id multi_file_edit `
  --cost-usd 69.18 `
  --startup-context-tokens 45615 `
  --quality-summary "Multi-file edit artifact shape preserved" `
  --validation-command "python -m pytest scripts/tests"
```

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl" `
  --output design/baselines/b0_sessions/research_plan.json `
  --session-id research_plan `
  --cost-usd 154.78 `
  --startup-context-tokens 44565 `
  --quality-summary "Research-plan artifact shape preserved" `
  --validation-command "python -m pytest scripts/tests"
```

Then:

```powershell
python scripts/session_cost_probe.py mixed-baseline `
  --output design/baselines/workflow_os_b0_mixed_sessions.json `
  --session-json design/baselines/b0_sessions/read_heavy_audit.json `
  --session-json design/baselines/b0_sessions/multi_file_edit.json `
  --session-json design/baselines/b0_sessions/research_plan.json
```

## Validation

The generated mixed baseline should now pass:

```powershell
python scripts/session_cost_probe.py b0-status `
  --baseline design/baselines/workflow_os_b0_mixed_sessions.json
```

Expected result: `ready=true` with exactly `read_heavy_audit`, `multi_file_edit`, and `research_plan`.
