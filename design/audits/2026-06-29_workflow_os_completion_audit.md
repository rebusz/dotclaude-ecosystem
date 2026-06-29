# Workflow OS Completion Audit

Date: 2026-06-29
Risk: R0 audit/readback
Parent plan: `design/plans/2026-06-27_global_agent_workflow_os.md`

## Verdict

The full Workflow OS plan is not complete.

The implemented scope is landed through `main` and validated, but several plan requirements are intentionally gated by external data or operator approval. This audit prevents accidental scope shrinkage: completed slices stay closed, and the remaining gates stay explicit.

## Current Repo Readback

- `dotclaude-ecosystem`: pre-audit baseline was `main == origin/main` at `ec239d5`.
- Dirty boundary: `skills/master-agent/SKILL.md` is operator WIP and remains outside Workflow OS commits.
- `python scripts/session_cost_probe.py check --baseline design/baselines/workflow_os_a1_baseline.json`
  - `claude_global`, `codex_global`, `cline_global`, `antigravity_global`: `kernel_ok=true`
  - `sync_check.ok=true`
  - zero drift against A1 baseline
- `python scripts/write_segregation_manifest.py validate design/security/write_segregation_path_manifest.json`
  - `entry_count=24`
  - repos: `D:/APPS/TSU`, `D:/APPS/Tsignal 5.0`
  - classes: `live-brain-only`, `operator-only`, `read-only-for-agents`, `write-allowed-for-agents`
- `python scripts/idea_digest.py workflow-triggers --file design/workflow_os_revisit_triggers.json`
  - `completed=4`
  - `deferred=1`
  - `manual=4`
  - `triggered=0`
  - `blocked=0`

## Requirement Status

| Requirement / gate | Status | Evidence | Remaining condition |
| --- | --- | --- | --- |
| Slice 0 kernel-slim and fail-closed guard | Complete | `design/handoffs/2026-06-28_workflow_os_slice0_handoff.md`; A1 check reports global kernels present and sync check OK | None for shipped Slice 0 |
| A1 runtime kernel drift check | Complete | `design/baselines/workflow_os_a1_baseline.json`; current `session_cost_probe.py check` zero drift | None for current globals |
| Slice 0b advisory tooling | Complete for approved R0/R1 scope | `design/handoffs/2026-06-29_workflow_os_slice0b_readback.md`; trigger board marks `slice-0b-after-tsu-pr-141` completed | R2 markitdown push-wiring remains separate |
| MarkItDown A2 harness | Complete as fixture/tool-path measurement | `scripts/markitdown_measure.py`; `design/measurements/2026-06-29_markitdown_a2_fixture_report.json` | Real operator corpus benchmark still needs real PDF/XLSX corpus |
| last30days additivity check | Complete for Slice 0b gate | Slice 0b readback and trigger board completed status | Future use still advisory/research-plane only |
| mattpocock skills reinstall and index refresh | Complete | Slice 0b readback; `docs/SKILLS_INDEX.md` | None for shipped scope |
| Tokencost decision | Complete: native logger default | `design/decisions/2026-06-29_tokencost_native_logger.md` | Adopting tokencost proxy would require separate risk acceptance |
| Cursor platform wiring | Complete | trigger board marks `cursor-platform-wiring` completed | None for current verified-high surface |
| Cline global sync | Complete | `design/handoffs/2026-06-29_cline_global_sync.md`; A1 check shows `cline_global.kernel_ok=true` | Repo-local Cline propagation is a later explicit per-repo sync slice |
| Antigravity global sync | Complete | `design/handoffs/2026-06-29_antigravity_global_sync.md`; A1 check shows `antigravity_global.kernel_ok=true` | MCP/hooks remain unwritten later slice |
| B0 mixed-session baseline | Incomplete / external data gate | `design/handoffs/2026-06-29_workflow_os_b0_capture_contract.md`; `design/handoffs/2026-06-29_workflow_os_b0_candidate_inventory.md`; trigger board keeps Headroom/RTK deferred | Pick 3 sessions and provide exact `/cost` for `read_heavy_audit`, `multi_file_edit`, `research_plan`; then generate `design/baselines/workflow_os_b0_mixed_sessions.json` |
| Headroom/RTK benchmark | Deferred | trigger board reason: missing `design/baselines/workflow_os_b0_mixed_sessions.json` | B0 mixed-session baseline must exist and pass review |
| Capability registry live file/status surface | Deferred by design | Plan section 10 and CEO amendment: do not build live registry until at least 3 gated tools pass section 9 | Needs >=3 gated tools to pass section 9, then generated registry only |
| Impeccable layer | Manual trigger | trigger board marks `impeccable-layer` manual | Start a real GUI/web build; evaluate against `tsu-dashboard-taste` boundary |
| deer-flow research layer | Manual/R2 trigger | trigger board marks `deer-flow-after-paper-week` manual | PAPER WEEK shipped and LAB research outgrows `/deep-research` + `/fusion`; create separate TsignalLAB advisory-only plan |
| autoresearch GPU host | Manual/R2 trigger | trigger board marks `autoresearch-gpu-host` manual | PAPER WEEK shipped and overnight GPU host exists; create separate TsignalLAB candidate-store plan |
| Section 3.7 write-segregation plan | Advanced, not applied | `design/plans/2026-06-29_mechanical_write_segregation_safety.md`; `design/audits/2026-06-29_mechanical_write_segregation_inventory.md`; `design/security/write_segregation_path_manifest.json`; `scripts/write_segregation_manifest.py` | Real write-deny still needs concrete Windows agent identity, quiesced TSU/Tsignal repo truth, dry-run review, then explicit R2/R3 operator GO before any apply |
| No trading repo/order-path writes from Workflow OS | Preserved | Work landed only in `dotclaude-ecosystem`; TSU/Tsignal dirty states are pre-existing operator/other-agent work | Continue preserving boundary |

## Remaining Gates In Order

1. **B0 external cost collection:** choose three representative TSU JSONL sessions and provide exact `/cost` values. This is the only way to unblock Headroom/RTK without inventing prices.
2. **Section 3.7 identity decision:** name the Windows agent identity or launcher profile for coding/advisory agents. Then generate a reviewed dry-run ACL artifact; do not apply it without explicit R2/R3 operator GO.
3. **Manual triggers:** wait for real GUI/web build, PAPER WEEK/LAB research triggers, or >=3 section-9-passing gated tools before touching Impeccable/deer-flow/autoresearch/capability-registry.

## Do Not Mark Complete Until

- `design/baselines/workflow_os_b0_mixed_sessions.json` exists from measured sessions with explicit `/cost`, and Headroom/RTK benchmark status has been resolved.
- Section 3.7 is either explicitly closed as plan-only by the operator or advanced through its R2/R3 approval chain with validated dry-run/apply/rollback evidence.
- Manual deferred slices have either fired and been handled, or the operator explicitly declares them out of scope for this plan.
