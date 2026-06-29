# Workflow OS B0 Selected Session Candidates

Date: 2026-06-29
Risk: R1 measurement prep
Status: cost readback required

## Purpose

This packet narrows the B0 baseline gate from "choose three sessions" to three selected local TSU-adjacent Claude JSONL candidates. It does not create `design/baselines/workflow_os_b0_mixed_sessions.json` and does not estimate `cost_usd`.

Machine-readable selection:

```text
design/baselines/b0_sessions/2026-06-29_selected_candidates.json
```

## Selected Candidates

| B0 class | JSONL file | Why this one |
| --- | --- | --- |
| `read_heavy_audit` | `f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl` | Read/Grep/Glob/PowerShell-heavy TSU/EcosystemControl audit shape with minimal edits. |
| `multi_file_edit` | `5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl` | Edit-heavy workflow touching shared fusion/audit plan/tooling files. |
| `research_plan` | `e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl` | Architecture/research planning session with Workflow/Agent use and TSU/Tsignal plan artifacts. |

The larger `a2789764-b080-4b74-be74-bb17db55652e.jsonl` was not selected because its metadata shows substantial WatchF work, so it is weaker as a TSU B0 representative despite the largest token total.

## Required Next Input

For each selected session, obtain the exact Claude `/cost` readback from the original session context. Do not infer price from token counts.

## Build Commands After Cost Readback

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl" `
  --output design/baselines/b0_sessions/read_heavy_audit.json `
  --session-id read_heavy_audit `
  --cost-usd <exact-cost-readback> `
  --startup-context-tokens <fresh-context-token-count> `
  --quality-summary "Read-heavy audit artifact shape preserved" `
  --validation-command "python -m pytest scripts/tests"
```

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl" `
  --output design/baselines/b0_sessions/multi_file_edit.json `
  --session-id multi_file_edit `
  --cost-usd <exact-cost-readback> `
  --startup-context-tokens <fresh-context-token-count> `
  --quality-summary "Multi-file edit artifact shape preserved" `
  --validation-command "python -m pytest scripts/tests"
```

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl" `
  --output design/baselines/b0_sessions/research_plan.json `
  --session-id research_plan `
  --cost-usd <exact-cost-readback> `
  --startup-context-tokens <fresh-context-token-count> `
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

Until exact `/cost` values are supplied:

```powershell
python scripts/session_cost_probe.py b0-status `
  --baseline design/baselines/workflow_os_b0_mixed_sessions.json
```

must remain fail-closed unless the current shipped-scope closure artifact is explicitly being used by `scripts/workflow_os_completion.py`.
