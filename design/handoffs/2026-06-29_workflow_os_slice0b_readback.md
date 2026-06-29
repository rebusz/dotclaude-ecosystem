# Workflow OS Slice 0b Readback

**Date:** 2026-06-29
**Scope:** R0/R1 advisory tooling after TSU PR #141 merged.

## Completed

- Added R0-only mechanical write-segregation safety plan:
  - `design/plans/2026-06-29_mechanical_write_segregation_safety.md`
  - Real permission/order-path implementation remains R2/R3 and gated by explicit operator GO.
- Added `scripts/session_cost_probe.py` and baseline:
  - `design/baselines/workflow_os_a1_baseline.json`
  - Kernel presence is true for global Claude and Codex files.
  - `sync_agent_rules.py --check --quiet` passed during baseline.
- Added Workflow OS revisit triggers:
  - `design/workflow_os_revisit_triggers.json`
  - `python scripts/idea_digest.py workflow-triggers`
  - Scheduled dry-run wrapper now records trigger summary beside git hygiene output.
- Added MarkItDown A2 measurement harness:
  - `scripts/markitdown_measure.py`
  - generated fixtures under `design/measurements/fixtures/`
  - report: `design/measurements/2026-06-29_markitdown_a2_fixture_report.json`
- Installed/verified advisory tools outside repo:
  - `markitdown[pdf,xlsx]==0.1.6`
  - `last30days@last30days-skill` enabled in Claude plugins
  - mattpocock skills reinstalled for Claude Code, Codex, and Cursor:
    - `diagnosing-bugs`
    - `tdd`
    - `domain-modeling`
    - `codebase-design`
    - `prototype`
    - `improve-codebase-architecture`
    - `handoff`
    - `triage`
- Regenerated `docs/SKILLS_INDEX.md`.
- Tokencost proxy rejected as default; native logger decision recorded:
  - `design/decisions/2026-06-29_tokencost_native_logger.md`
- Headroom/RTK benchmark trigger corrected:
  - it now waits for `design/baselines/workflow_os_b0_mixed_sessions.json`
  - the A1 kernel baseline alone is not a valid mixed-session proxy benchmark gate.

## Important Limitations

- No existing `.pdf` or `.xlsx` corpus files were found under `D:/APPS` or `D:/dotclaude` by `rg --files`, so the MarkItDown report is a fixture-based tool-path check, not an operator-corpus benchmark.
- Cline and Antigravity remain unimplemented because their plan entries require live-install verification first.
- Headroom/RTK remain deferred because no B0 mixed-session baseline exists yet.
- No per-repo `sync --write --repo X` was run.
- No trading repo runtime/order/broker path was edited.
- `skills/master-agent/SKILL.md` in this repo remains operator WIP and must not be staged.

## Evidence Commands

```powershell
python scripts/session_cost_probe.py check --baseline design/baselines/workflow_os_a1_baseline.json
python scripts/idea_digest.py workflow-triggers
python scripts/markitdown_measure.py design/measurements/fixtures/workflow_os_fixture.pdf design/measurements/fixtures/workflow_os_fixture.xlsx --expect-term "Workflow" --expect-term "measurement" --output design/measurements/2026-06-29_markitdown_a2_fixture_report.json
claude plugin list
npx skills@latest list -g --json
python scripts/skills_index.py
```
