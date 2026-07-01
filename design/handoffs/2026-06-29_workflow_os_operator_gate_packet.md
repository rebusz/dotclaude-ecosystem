# Workflow OS Operator Gate Packet

Date: 2026-06-29
Risk: R0 handoff/readback
Parent audit: `design/audits/2026-06-29_workflow_os_completion_audit.md`

## Purpose

The shipped Workflow OS scope is landed and validated, but the full plan cannot complete without external operator inputs. This packet condenses the remaining gates into exact actions and commands. It does not apply ACLs, does not create a B0 baseline, and does not touch TSU/Tsignal runtime or order paths.

## Gate 1: B0 Mixed-Session Baseline

Generated artifact:

```text
design/baselines/workflow_os_b0_mixed_sessions.json
```

Completed inputs:

- Chosen session for `read_heavy_audit`: `f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl`.
- Chosen session for `multi_file_edit`: `5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl`.
- Chosen session for `research_plan`: `e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl`.
- Exact Claude Stop hook `$... sess` cost readbacks recovered locally: `$36.78`, `$69.18`, `$154.78`.

Completed startup-context input:

- `read_heavy_audit`: `48871`
- `multi_file_edit`: `45615`
- `research_plan`: `44565`

Candidate inventory:

```text
design/handoffs/2026-06-29_workflow_os_b0_candidate_inventory.md
```

Selected candidate packet:

```text
design/handoffs/2026-06-29_workflow_os_b0_selected_sessions.md
```

Cost readback artifact:

```text
design/baselines/b0_sessions/2026-06-29_selected_cost_readbacks.json
```

Measured session JSON commands used:

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\<session>.jsonl" `
  --output design/baselines/b0_sessions/<session-class>.json `
  --session-id <read_heavy_audit|multi_file_edit|research_plan> `
  --cost-usd <exact-cost-readback> `
  --startup-context-tokens <operator-confirmed-first-assistant-context-footprint> `
  --quality-summary "<artifact equivalence summary>" `
  --validation-command "<command that proves artifact quality>"
```

Generate the real B0 baseline only after all three measured session JSON files exist:

```powershell
python scripts/session_cost_probe.py mixed-baseline `
  --output design/baselines/workflow_os_b0_mixed_sessions.json `
  --session-json design/baselines/b0_sessions/read_heavy_audit.json `
  --session-json design/baselines/b0_sessions/multi_file_edit.json `
  --session-json design/baselines/b0_sessions/research_plan.json
```

Then re-run:

```powershell
python scripts/idea_digest.py workflow-triggers --file design/workflow_os_revisit_triggers.json
```

Current effect: `headroom-rtk-benchmark` has now run as a measurement-only R1 slice and is parked, not enabled by default.

Readiness check:

```powershell
python scripts/session_cost_probe.py b0-status `
  --baseline design/baselines/workflow_os_b0_mixed_sessions.json
```

Expected current result: zero exit with `ready=true` because the measured B0 baseline exists and contains exactly `read_heavy_audit`, `multi_file_edit`, and `research_plan`.

## Gate 2: Section 3.7 Write-Segregation Identity

Blocked artifact:

```text
design/security/<reviewed-dry-run-acl-plan>.json
```

Observed candidate:

```text
design/security/2026-06-29_observed_codex_identity_acl_dry_run.json
```

Refreshed candidate:

```text
design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Detailed apply runbook:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_runbook.md
```

Apply/rollback review packet:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md
```

This candidate was generated from the current Codex process identity `pc-tsignal-flow\dszub`. It is review-only: `applies_acl=false` and `requires_operator_go_before_apply=true`.

Required operator input:

- Confirm that `pc-tsignal-flow\dszub` is the intended Windows identity for coding/advisory agents, or provide the exact launcher profile to use instead, for example `<MACHINE>\<agent-user>` or `<DOMAIN>\<agent-user>`.

Current manifest:

```text
design/security/write_segregation_path_manifest.json
```

Validate the manifest:

```powershell
python scripts/write_segregation_manifest.py validate design/security/write_segregation_path_manifest.json
```

Generate a review-only dry-run ACL artifact after identity is known:

```powershell
python scripts/write_segregation_manifest.py dry-run-acl `
  design/security/write_segregation_path_manifest.json `
  --agent-identity "<DOMAIN-or-MACHINE>\<agent-user>" `
  --output design/security/<reviewed-dry-run-acl-plan>.json
```

Validate the generated dry-run artifact:

```powershell
python scripts/write_segregation_manifest.py validate-dry-run `
  design/security/<reviewed-dry-run-acl-plan>.json `
  --manifest design/security/write_segregation_path_manifest.json
```

Run the full pre-apply check against the reviewed packet:

```powershell
python scripts/write_segregation_manifest.py preapply-check `
  --manifest design/security/write_segregation_path_manifest.json `
  --dry-run design/security/<reviewed-dry-run-acl-plan>.json `
  --packet design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md `
  --allow-dirty skills/master-agent/SKILL.md
```

If TSU or Tsignal is intentionally reviewed on a clean non-default branch, add an explicit `--allow-branch "<repo>=<git-status-branch-line>"` argument.

Apply evidence template:

```text
design/security/2026-07-01_section37_apply_evidence_template.json
```

Validate future pilot/batch evidence:

```powershell
python scripts/write_segregation_manifest.py validate-apply-evidence `
  design/security/<section37-apply-evidence>.json `
  --dry-run design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Important: the generated dry-run artifact still has `applies_acl=false`. Do not execute any generated `icacls` command without:

- quiesced TSU and Tsignal repos,
- default or explicitly accepted TSU/Tsignal branches,
- refreshed path manifest from live repo truth,
- passing `validate-dry-run` preflight,
- passing `preapply-check` preflight,
- reviewed rollback commands,
- passing `validate-apply-evidence` after pilot/batch execution,
- explicit R2/R3 operator GO naming the apply step.

## Gate 3: Manual Deferred Triggers

These remain manual and must not be pulled forward silently:

- `impeccable-layer`: only when a real GUI/web build starts.
- `deer-flow-after-paper-week`: only after PAPER WEEK ships and LAB research outgrows `/deep-research` plus `/fusion`.
- `autoresearch-gpu-host`: only after PAPER WEEK ships and an overnight GPU host exists.
- `capability-registry-generated`: only after at least three gated tools pass section 9.

## Current Safe Stop

If no operator input is available, stop here. The shipped Workflow OS scope is complete, but do not mark Section 3.7 apply complete and do not invent Windows identities, quiesced repo state, or manual trigger readiness.

## Follow-up Readback: Headroom/RTK

Completed after this packet:

```text
design/handoffs/2026-07-01_workflow_os_headroom_rtk_readback.md
design/measurements/2026-07-01_headroom_rtk_benchmark_report.json
```

Decision: `PARK`. No proxy, wrapper, hook, or global default was enabled.

## Follow-up Readback: Remaining Gates

Current remaining-gates status:

```text
design/handoffs/2026-07-01_workflow_os_remaining_gates_readback.md
```

Current status for Section 3.7 apply: `D:/APPS/TSU` is clean on `master == origin/master`, `D:/APPS/Tsignal 5.0` is clean on `main == origin/main`, and the refreshed ACL artifact is review-only with `applies_acl=false`. Real ACL writes still require operator identity confirmation, rollback review, probes, and a separate R2/R3 apply GO.
