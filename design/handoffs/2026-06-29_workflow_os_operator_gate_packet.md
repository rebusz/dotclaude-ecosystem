# Workflow OS Operator Gate Packet

Date: 2026-06-29
Risk: R0 handoff/readback
Parent audit: `design/audits/2026-06-29_workflow_os_completion_audit.md`

## Purpose

The shipped Workflow OS scope is landed and validated, but the full plan cannot complete without external operator inputs. This packet condenses the remaining gates into exact actions and commands. It does not apply ACLs, does not create a B0 baseline, and does not touch TSU/Tsignal runtime or order paths.

## Gate 1: B0 Mixed-Session Cost Collection

Blocked artifact:

```text
design/baselines/workflow_os_b0_mixed_sessions.json
```

Required operator inputs:

- Choose exactly one session for `read_heavy_audit`.
- Choose exactly one session for `multi_file_edit`.
- Choose exactly one session for `research_plan`.
- For each chosen session, provide exact Claude `/cost` readback.
- Provide or confirm `startup_context_tokens` for the fresh-context probe used with those sessions.

Candidate inventory:

```text
design/handoffs/2026-06-29_workflow_os_b0_candidate_inventory.md
```

Generate one measured session JSON after a `/cost` value is known:

```powershell
python scripts/session_cost_probe.py jsonl-session `
  --jsonl "$env:USERPROFILE\.claude\projects\D--APPS-TSU\<session>.jsonl" `
  --output design/baselines/b0_sessions/<session-class>.json `
  --session-id <read_heavy_audit|multi_file_edit|research_plan> `
  --cost-usd <exact-cost-readback> `
  --startup-context-tokens <fresh-context-token-count> `
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

Expected effect: `headroom-rtk-benchmark` can stop being deferred only if the mixed-session baseline exists and passes review.

## Gate 2: Section 3.7 Write-Segregation Identity

Blocked artifact:

```text
design/security/<reviewed-dry-run-acl-plan>.json
```

Observed candidate:

```text
design/security/2026-06-29_observed_codex_identity_acl_dry_run.json
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

Important: the generated dry-run artifact still has `applies_acl=false`. Do not execute any generated `icacls` command without:

- quiesced TSU and Tsignal repos,
- refreshed path manifest from live repo truth,
- reviewed rollback commands,
- explicit R2/R3 operator GO naming the apply step.

## Gate 3: Manual Deferred Triggers

These remain manual and must not be pulled forward silently:

- `impeccable-layer`: only when a real GUI/web build starts.
- `deer-flow-after-paper-week`: only after PAPER WEEK ships and LAB research outgrows `/deep-research` plus `/fusion`.
- `autoresearch-gpu-host`: only after PAPER WEEK ships and an overnight GPU host exists.
- `capability-registry-generated`: only after at least three gated tools pass section 9.

## Current Safe Stop

If no operator input is available, stop here. Do not mark the full Workflow OS plan complete, and do not invent B0 costs, Windows identities, or manual trigger readiness.
