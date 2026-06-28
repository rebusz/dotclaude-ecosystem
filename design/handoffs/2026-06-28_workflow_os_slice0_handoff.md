# HANDOFF — Agent Workflow OS / Slice 0 kernel-slim | R0 (this doc) · Slice 0 was R1 | 2026-06-28 ~12:15 MDT

## Repo/cwd
- Primary: `D:/dotclaude/dotclaude-ecosystem` (the agent-config monorepo — single checkout, NOT a worktree).
- Session ran from worktree `D:/APPS/TSU/.claude/worktrees/crazy-tesla-1d9a96` (branch `claude/crazy-tesla-1d9a96`), but ALL work landed in dotclaude-ecosystem + live `~/.claude` / `~/.codex`.

## Branch/HEAD
- `dotclaude-ecosystem` main @ `8388122` (Slice 0 #2) — local main fast-forwarded to origin/main. Clean & pushed.
- Plan + Slice 0 both merged (PR #1 `86a74c7`, PR #2 `8388122`); PR branches deleted.

## Dirty tree
- `dotclaude-ecosystem`: only `skills/master-agent/SKILL.md` (M) — **operator WIP, deliberately untouched** all session. Stage NOTHING else with it.
- Live files edited outside any repo (the slim's effect): `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.claude/refs/audit-aliases.md` (new), `~/.claude/ARCHIVE.md` (new), `~/.claude/projects/D--APPS-TSU/memory/{MEMORY.md,ARCHIVE.md}`.

## Done
- **Project framed + planned:** cross-platform Agent Workflow OS (Claude Code/Codex/Cursor/Cline/Antigravity) EXTENDING dotclaude-ecosystem. Plan: `design/plans/2026-06-27_global_agent_workflow_os.md`.
- **Grounded by research workflow `wpanit7jb`** (36 agents: 25 repo verdicts + 5 platform surfaces + 8 dedup + adversarial critic). Key kills: keep `code-review-graph` (SKIP codebase-memory-mcp); SKIP `leonxlnx/taste-skill` (byte-identical fork); tokencost→native-logger default; markitdown OUT of the secret-egress sanitizer path; Cline=no-Win-hooks + Antigravity=`serverUrl` footgun → DO-NOT-IMPLEMENT-unverified.
- **Design-gate sequence COMPLETE** — `/plan-ceo-review` + `/fusion matrix` (9/14 lanes; CDP fleet down) + `/plan-eng-review`, all **GO-WITH-AMENDMENTS**, all amendments folded into the plan. Matrix added: Artifact-Bus downscope, runtime kernel-presence drift check, §3.7 mechanical write-segregation. Eng caught 3 mechanical §6a fixes (edit SOURCE not rendered; guard was fail-OPEN; ~28-file fan-out).
- **Slice 0 (kernel-slim) SHIPPED:** core.md deep procedures (Token Budget Protocol + Trading data-flow detail) → `agent-rules/refs/`; audit aliases → `~/.claude/refs/audit-aliases.md`; stale Micro-Skill block → `~/.claude/ARCHIVE.md`; **`~/.claude/CLAUDE.md` 17,815 → 15,005 B (−2,810)**, `~/.codex/AGENTS.md` slimmed; `MEMORY.md` 4 closed entries → its ARCHIVE (no loss). **Fail-closed guard:** `scripts/sync_agent_rules.py` claude-global spec now `line_limit=162` + new `byte_limit=16000`.
- Memory updated: `project-agent-workflow-os` (SHIPPED), `MEMORY.md` index, 4 entries archived.

## Validation
- `python -m pytest scripts/tests/` → **40/40 pass**.
- `sync_agent_rules.py --check` (globals) → clean & within limits (exit 0).
- Guard **proven fail-closed**: a +1.3 KB regrowth probe raised `16331 bytes exceeds limit 16000` (exit 1); CLAUDE.md restored.
- Merges confirmed `state=MERGED`; local main ff confirmed; income repos `TSU`/`Tsignal` AGENTS.md mtimes unchanged (untouched).
- Raw artifacts: workflow outputs under the session `tasks/` dir (`wpanit7jb`, `wwzi348v4`, `byfznfsls`, `wfu402xzm`); fusion run `~/.claude/fusion_runs/2026-06-27_155603_*`.

## Blocker/stop reason
- Slice 0 done; everything past it is **gated behind the §0 opportunity-cost gate (after TSU PR #141 income blocker)** — this is advisory meta-infra, does not advance PAPER WEEK.
- §3.7 mechanical write-segregation is an **open operator decision** (its own R2/R3 safety plan).

## No-go boundaries
- Research/memory/design planes stay **ADVISORY-ONLY**; LLM agents never touch broker API or order path.
- **Do NOT run per-repo `sync --write --repo X`** as a side-effect — core.md now DRIFTS vs the 13 repos' fat managed blocks; resolving it dirties income repos (TSU/Tsignal). It is a deliberate, idempotent follow-up, not automatic. Daily git_hygiene janitor won't auto-propagate (DRY-RUN).
- §3.7 OS-level write-deny touches live-trading config/order-path file perms → **R2/R3, needs explicit operator GO**; do not implement on a bare "go".
- Never stage `skills/master-agent/SKILL.md` (operator WIP).

## Next token (pick one; refresh repo truth first)
- `GO §3.7 (R0 plan only)` — draft `design/plans/<date>_mechanical_write_segregation_safety.md`: OS-level write-deny on `D:/APPS/TSU` + `D:/APPS/Tsignal 5.0` order/runtime/strategy paths; advisory→live only via the existing gated seam; enforce `plane`/`risk_class` at load time. Plan is R0; implementation stays gated.
- `GO Slice 0b (R1, AFTER PR #141)` — markitdown (measurement-only, Anthropic-tokenizer delta + fidelity; keep OUT of sanitizer path) · last30days (gated by Perplexity-recency dedup) · mattpocock reinstall (+ grep old slash-names) · tokencost decision (native logger default).
- `GO per-repo re-sync` — `python ~/.claude/scripts/sync_agent_rules.py --write --repo "<path>"` per repo to clear the managed-block drift (expect ~2 files/repo; avoid income repos while PR #141 is live).
- Before executing any: refresh branch/HEAD, dirty tree, plan context (`plan_context_loader.py`), and the advisory-only / order-path safety contracts.
