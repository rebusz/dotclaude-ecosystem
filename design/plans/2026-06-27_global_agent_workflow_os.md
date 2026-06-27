# Global Agent Workflow OS — Architect Plan

**Grade:** R0 (docs + prompts + advisory tooling only; each slice re-stamps its own risk class)
**Scope:** EXTENDS `dotclaude-ecosystem` — no new repo, no new agent runtime, no change to any live/order/runtime trading state.
**Date:** 2026-06-27 · **Status:** PLAN (awaiting `/plan-eng-review` + operator implement GO)
**Source research:** workflow `wpanit7jb` (36 agents, 25 repo verdicts + 5 platform surfaces + 8 dedup verdicts + adversarial critique). Findings folded in below.

---

## 0. North-Star alignment & the opportunity-cost decision (READ FIRST)

**This is advisory meta-infrastructure. It does NOT advance the PAPER WEEK income gate.**
The operator's #1 income blocker is the `_close_p2_lifecycle` fetch_stops race (TSU PR #141, awaiting implement GO) sitting between the armed brain and funded-trading income. Nothing in this plan moves that needle.

Token burn is a real cost that taxes *every* future session (including all income-path work), so a **bounded** investment here is legitimate — but only if scoped consciously. Therefore:

- **Slice 0 (kernel-slim, R0, ~30 min)** is the only item that is net-positive even mid-income-sprint: it makes every subsequent session (income work included) cheaper, with zero runtime risk. **This is the recommended "do it now" floor.**
- **Slice 0b (markitdown-measure / last30days / mattpocock / tokencost-decision)** and everything below should be **sequenced AFTER TSU PR #141 lands**, or explicitly chosen over income work by the operator.

> **DECISION GATE (operator):** (a) kernel-slim now + defer the rest until after PR #141 [recommended], (b) full Slice 0 + 0b now, or (c) defer the entire OS until PAPER WEEK ships.

---

## 1. Goals & Non-Goals

**Goals**
1. Cut token burn while improving code quality.
2. Hybrid **on-demand** skill + architecture across Claude Code, Codex, Cursor, Cline, Antigravity — with memory, session hygiene, and a curated plan/audit/implement/review skill set.
3. Advanced research systems (coding-research + domain/market-research), integrated with Obsidian Flow.
4. Design system for GUI/web consistency.

**Non-Goals**
- A new config silo (we already have three: `dotclaude-ecosystem`, `ecosystem-context`, `~/.claude`). We extend, not add.
- A new always-on agent runtime (Hermes/DeerFlow-as-daemon) anywhere near the live path.
- ANY write to live/order/runtime trading state. Ever.

---

## 2. Architecture spine

```
THIN HOT KERNEL  (slim core.md + overlays — invariants only, zero deep procedure)
      │  risk policy · repo truth · mode router · token budget · skill-registry pointer
      ▼
INTENT ROUTER  (plan_keyword_detector + master-agent modes — already exists)
      ▼
CAPABILITY REGISTRY   (NEW: D:/APPS/_shared/agent_capabilities.yaml)
      │  name · plane · vector · latency_class · provider_ref · risk_class · enabled · health_check
      ▼
ON-DEMAND SKILL PACKS   (plan · audit · implement · token-diet · research · memory · design)
      ▼
ARTIFACT BUS   (packets · audits · handoffs)  ──►  OBSIDIAN FLOW (memory / readback)
      │
      ├─ token plane        (minify-first; benchmark-gated proxies)
      ├─ repo-graph plane   (KEEP code-review-graph incumbent)
      ├─ research plane      (TsignalLAB: deer-flow / autoresearch / Vibe-Trading patterns) ··advisory only··
      ├─ memory plane        (claude-mem + ecosystem-context + Obsidian Flow)
      └─ design plane         (taste family + impeccable layer + Figma/Penpot)
      ▼
   CODEX / CLAUDE TRIAGE  ──►  ⛔ TSU/Tsignal LIVE AUTHORITY (isolated, never written)
```

---

## 3. HARD BOUNDARY (no-go) — the contract every slice obeys

1. Research + memory + design planes are **ADVISORY-ONLY**; they never write live/order/runtime state.
2. LLM agents never touch broker API or order path.
3. Token proxies (tokencost / headroom / rtk) are **dev-profile only**, never on a trading-adjacent Claude Code session, never a global `ANTHROPIC_BASE_URL` intercept (that routes *every* agent through one SPOF + silent model downgrade).
4. `deer-flow` / `autoresearch` are **TsignalLAB-only** and feed the candidate store via the existing validated async gated seam (candidate store → validation gate → shadow → signed operator GO).
5. **Secret-egress order is fixed:** any third-party parser (markitdown) runs **after** the ecosystem-context sanitizer on already-clean artifacts, OR its output is treated as untrusted and re-sanitized by an independent pass. A parser never sits between secret-bearing source and the strip. *(critique P1-d)*
6. **Kill-switch:** every proxy/MCP/skill added is removable by one documented env-var/config line.

---

## 4. Confirmed adoption matrix (evidence-grounded; README claims separated from evidence)

| Tier | Repos | Why |
|---|---|---|
| **ADOPT** | `mattpocock/skills` | Already known-good; local copies were deleted — this is a reinstall, not a new eval. |
| **PILOT — measurement-only first** | `microsoft/markitdown`, `mvanhorn/last30days-skill`, `pbakaus/impeccable` (gated layer) | Earn a permanent slot only after their measurement/dedup gate passes. |
| **BENCHMARK before default-on** | `headroomlabs-ai/headroom`, `rtk-ai/rtk` | Real token tools, but `rtk` issue #582 shows output inflation can flip a 60-90% *input* win into **+18% total cost**. Measure input+output+total. |
| **EVAL-VS-EXISTING / SKIP (dedup)** | `codebase-memory-mcp` (skip — incumbent live), `ponytail` (always-on contradicts progressive-disclosure), `honey-for-devs`, `Understand-Anything`, `sdl-mcp` (fd-leak blocker), `ArcRift` (→skip), `leonxlnx/taste-skill` (byte-identical fork) | Overlap with existing stack; see §5 dedup. |
| **REFERENCE (mine the pattern, don't connect)** | `karpathy/autoresearch` (3-file ratchet loop), `HKUDS/Vibe-Trading` (Alpha-Zoo purity-gate + Shadow-Account), `NousResearch/hermes-agent` (CC-orchestration SKILL.md only) | Patterns for TsignalLAB; never wired to a live session. |
| **WATCH** | `tokencost` (analytics-only, gated — see §6c), `deer-flow`, `open-notebook`, `vllm`, `penpot` | Revisit on a concrete trigger (§8), not "someday." |
| **SKIP** | `smallcode` (solves a local-LLM problem we don't have), `devspace` (ChatGPT-access; not a wired platform; Bash-only breaks on Windows), `fable-mode` (covered by master-agent+executor; unlicensed) | No seam / negative risk-benefit. |

**Net "now" set:** ADOPT `mattpocock/skills` (reinstall). Everything else is gated, deferred, or killed.

---

## 5. Dedup verdicts (decisive — avoid stacking duplicates)

- **codebase-memory-mcp vs code-review-graph (incumbent v2.3.2): SKIP proposed.** Incumbent is live across 6 repos (TSU graph: 2,065 nodes / 32,613 edges, 2026-06-23) and already has vector embeddings + `semantic_search_nodes_tool`. CLAUDE.md forbids two competing graphs. 158-language breadth is irrelevant (Python/TS only). Revisit on microservice/non-Python pivot.
- **leonxlnx/taste-skill vs vendored design-taste-frontend: SKIP.** Byte-identical source (88,459 B) vs leonxlnx's 87,126 B stale fork. Keep vendor tracking the canonical upstream.
- **impeccable vs taste-skill family: COMPLEMENT-AS-LAYER (gated).** Covers the product-UI register taste-skills exclude (dashboards/admin/app-shells), adds PRODUCT.md/DESIGN.md anchor + OKLCH + 27 scoped commands. **Gate:** impeccable's `animate`/`delight`/`overdrive` must never fire on TSU cockpit live-data files; reconcile its font reflex-reject list vs taste allowed-pool via `.taste.json` precedence.
- **open-notebook vs ecosystem-context + Obsidian Flow: SKIP.** Corpus-chat niche, no seam into the sanitizer/MEMORY/VISIONS/PLANS schema.
- **ArcRift vs claude-mem: SKIP.** Duplicate recall/store/search MCP surface; its only unique path (browser-chat capture) isn't the operator's workflow + needs Ollama.
- **hermes-agent vs entire stack: SKIP runtime, REFERENCE one doc.** Competing autonomous platform (cron, browser automation, IM gateway) with no isolation boundary from live trading. Cherry-pick `skills/autonomous-ai-agents/claude-code/SKILL.md` into the executor skill at most.
- **deer-flow / autoresearch vs master-agent + executor: COMPLEMENT-AS-LAYER (TsignalLAB only).** Different abstraction (research server vs prompt-layer engineering orchestration). Advisory research engines feeding the LAB candidate store; never replace engineering orchestration; deploy only if LAB research outgrows `/deep-research` + `/fusion`.
- **last30days vs Perplexity-recency (NEW, critique P2-b): KEEP only if additive.** Perplexity (wired via ecosystem-context) already covers recency-weighted web/social search. last30days earns a slot **only** if its *structured* Reddit/HN/Polymarket/GitHub lanes are genuinely additive over Perplexity's freeform recency — otherwise it's another idle skill.

---

## 6. Slice 0 — kernel-slim (R0, ~30 min) + Slice 0b (R1, gated, post-PR#141)

### 6a. Slice 0 — Thin-kernel refactor (R0, recommended "now")
**Current state (measured):** `~/.claude/CLAUDE.md` = 178 lines / 17,815 B; managed block (core.md + claude-global overlay) ≈ 12.5 KB; manual tail ≈ 5.3 KB. `MEMORY.md` auto-index = 15,107 B / **52 entries** (violates the operator's own hot/cold cap). `$CMEM` SessionStart ≈ 8,837 tok. Steering hook (conditional) ≈ 3,174 tok. **Σ fresh-session startup ≈ 20k tok before the task begins.**

**Moves (move, never delete — git + ARCHIVE keep history):**
1. **Stale Micro-Skill Routing block** (CLAUDE.md ~lines 154–169) — self-described as "NOT currently installed." Delete from kernel; the §6b-mattpocock reinstall makes it real. Archive to `~/.claude/ARCHIVE.md` if kept.
2. **Superseded audit aliases** (auditq/auditai/auditpx) — collapse to a one-line pointer; move the table to `~/.claude/refs/audit-aliases.md`.
3. **`core.md` surgery** (`agent-rules/core.md`): extract the *deep procedure* from `Token Budget Protocol` (8 bullets) and the `Trading data flow` seam into `agent-rules/refs/token-budget-protocol.md` + `refs/data-flow-seam.md`, leaving a 2-line invariant + pointer in `core.md`. Re-run `sync_agent_rules.py --write` across repos.
4. **MEMORY.md hot/cold cleanup** — move DONE/superseded entries (resolved blockers, merged PRs) to `ARCHIVE.md` per the operator's own rule. Target: index back under its load cap.

**Success metric (critique P2-f — bytes ≠ tokens):** the target is the **A1 measured fresh-session startup-token delta (direction-positive)**, captured via a `/context` probe — *not* a byte percentage. (Byte estimate ~12.5 KB → ~7 KB is a footnote, not the metric.)

### 6b. Slice 0b — advisory tooling (R1, sequence AFTER TSU PR #141)
- **markitdown — MEASUREMENT-ONLY (R1), then R2 to wire (critique P1-a, P1-d):** `pip install markitdown` (selective extras, not `[all]`). Slice-0b task is *only* the A2 delta: tokenize one plan PDF + one XLSX raw-vs-MD with the **Anthropic tokenizer** + verify fidelity. It earns a permanent pipeline slot in a later slice **only if** delta is positive AND fidelity holds. Any wiring into the ecosystem-context push path is **R2** and must run **downstream** of the sanitizer (or be independently re-sanitized).
- **last30days (R1, gated by §5 Perplexity dedup):** `/plugin marketplace add mvanhorn/last30days-skill`. Zero-config lanes only; skip X/TikTok key wizard. Advisory research plane.
- **mattpocock/skills reinstall (R0/R1):** `npx skills@latest add mattpocock/skills` (v1.0.0 taxonomy: diagnosing-bugs, tdd, domain-modeling, codebase-design, prototype, improve-codebase-architecture, handoff, triage). **Then grep all of `~/.claude/` for old slash names** (`/diagnose`→`/diagnosing-bugs`, `/zoom-out` removed) and fix every caller incl. CLAUDE.md + MEMORY refs *(critique P3-a)*.
- **tokencost — DECISION, default = native logger (critique P2-d):** the smart-routing auto-downgrade + `tracker.db` prompt-preview persistence make the proxy a secret-at-rest + auditability risk. **Default action: build a thin native token-logger from Claude Code's own `usage`/`/cost`.** Adopt the tokencost proxy **only if** (a) an analytics-only/routing-off mode exists AND (b) previews can be truncated to token-counts-only on a gitignored/deny-from-backup `tracker.db`. Otherwise SKIP.

---

## 7. Cross-platform wiring (verified surface + hard constraints)

| Platform | Skills | Hooks | MCP | Rules/mem file | On-demand? | Sync target |
|---|---|---|---|---|---|---|
| **Claude Code** | `~/.claude/skills/*/SKILL.md`, name+desc only at start, body lazy | Richest (25+ events) | First-class + ToolSearch defers schemas | `CLAUDE.md` managed block + `.claude/rules/*.md` | **YES (best)** | managed block (live) |
| **Codex CLI** | `.agents/skills/` index ≤2%/8KB, body lazy | Full lifecycle | `~/.codex/config.toml` | `AGENTS.md` chain (32KiB cap) + `AGENTS.override.md` | PARTIAL (rules eager) | sentinel block in `AGENTS.md` / `AGENTS.override.md` |
| **Cursor** | `.cursor/skills/` 3-tier, near-zero start | `.cursor/hooks.json` (beta) | `~/.cursor/mcp.json`, tool descs lazy | `.cursor/rules/*.mdc` (4 types) + native `AGENTS.md` | **YES** | `.mdc` frontmatter; AGENTS.md bridge |
| **Cline (VS Code)** | `.cline/skills/` meta ~100tok | ⚠️ **macOS/Linux ONLY — NO hooks on Windows** | user-only JSON, no project scope | `.clinerules/` + auto-reads `AGENTS.md` | PARTIAL | `.clinerules` + AGENTS.md (text only, **no hooks**) |
| **Antigravity** | `.agents/skills/` progressive | `.agents/hooks.json` | `mcp_config.json` ⚠️ **`serverUrl` not `url`** | `GEMINI.md` > `AGENTS.md` > `.agent/rules/` | YES (skills) | AGENTS.md + `GEMINI.md` overlay |

**Verified-high:** Claude Code, Codex, Cursor. **CONFIDENCE-MEDIUM / DO-NOT-IMPLEMENT-UNVERIFIED:** Cline + Antigravity — their path conventions come from third-party guides (official docs JS-rendered/unfetchable) and contain silent-failure footguns (`serverUrl`, Windows-no-hooks). **Slice 0 writes NO Cline/Antigravity sync target**; both are gated behind a "verify against a live install" task *(critique P1-c)*.

**Universal cheap target:** `AGENTS.md` managed-block (read natively by Codex/Cursor/Cline/Antigravity). **Caveat (critique P3-c):** for Claude Code, `@AGENTS.md` import is *not* free — it pulls the full file every session, defeating CC's best-in-class lazy loading. So CC keeps its own managed block and shares only **invariants** via AGENTS.md, not the full ruleset.

---

## 8. Deferred slices (each with a concrete revisit trigger — no silent rot)

| Item | Plane | Revisit trigger |
|---|---|---|
| Platform wiring: Cursor | cross-platform | After Slice 0 lands (verified-high; lowest friction) |
| Platform wiring: Cline / Antigravity | cross-platform | After a live-install verification task confirms paths |
| impeccable layer | design | When a real GUI/web build starts (gated vs `tsu-dashboard-taste`) |
| headroom / rtk benchmark | token | After kernel-slim; only if mixed-session total-cost gate (§9) is set up |
| deer-flow | research | When LAB research outgrows `/deep-research`+`/fusion` AND PAPER WEEK has shipped |
| autoresearch | research | When an overnight GPU host exists AND PAPER WEEK has shipped |
| codebase-memory-mcp | repo-graph | On microservice / non-Python pivot, or if incumbent semantic search proves insufficient |
| penpot / open-notebook / vllm | design/memory/infra | On a concrete need (Figma migration / corpus-chat / dedicated GPU host) |

---

## 9. Benchmark-gate for token proxies (the measurement discipline)

1. **B0 baseline:** 3 representative TSU sessions (read-heavy audit / multi-file edit / research-plan). Capture per-session `input/output/cache_read/cost` from CC `usage` + `/cost`; record kernel-load tokens via a fresh-session `/context` probe.
2. **A1 (after kernel-slim):** re-probe fresh-session startup tokens → the kernel-slim success metric.
3. **A2 (per proxy):** markitdown — Anthropic-tokenizer raw-vs-MD delta on real artifacts. headroom/rtk — measure **input + output + total cost** (rtk #582 lesson).
4. **Quality metric (critique P2-f):** "no regression" = the 3 B0 sessions re-run produce **functionally-equivalent artifacts** (same files changed, tests still pass, plan covers the same sections) — concrete pass/fail, not vibes.
5. **Ship gate:** a proxy goes default-ON only if **total cost ↓ ≥15%** on the mixed-session average **with no quality regression**. Input-only wins that raise output tokens are rejected.

---

## 10. Capability Registry schema (`D:/APPS/_shared/agent_capabilities.yaml`)

```yaml
- name: markitdown
  plane: research          # token | repo-graph | research | memory | design
  vector: library          # skill-markdown | mcp-server | cli-proxy-or-hook | library | engine-service | design-tool | reference-pattern
  latency_class: batch     # hot | warm | batch
  provider_ref: scripts/ingest_to_md.py
  risk_class: R2           # touches secret-egress when wired to push path
  enabled: false
  health_check: "python -c 'import markitdown'"
  kill_switch: "remove provider_ref + registry entry"
```

---

## 11. Lifecycle / reversibility

- **PRE:** `python ~/.claude/scripts/plan_context_loader.py --cwd <repo> --plan <this>`
- **Review gate:** R0 plan → `/plan-eng-review` (architecture/data-flow/sequencing) before any implement GO. R2 items (markitdown push-wiring) get their own review at promotion.
- **Rollback per item:** kernel-slim = `git revert` of the core.md/CLAUDE.md edits + re-run sync; every tool = one documented kill-switch line.
- **POST:** `python ~/.claude/scripts/plan_context_updater.py --plan <this> --shipped --note "<slice>"`

---

## 12. Open uncertainties (decision gates)

1. tokencost analytics-only mode — unverified; default to native logger unless confirmed.
2. markitdown real token delta + fidelity on the operator's corpus — measure before any permanent slot.
3. Kernel-slim loaded-token payoff — A1 probe required (byte ≠ token).
4. last30days additivity over Perplexity-recency — dedup gate.
5. Antigravity/Cline path conventions — verify against live install before writing any sync target.
6. Opportunity cost vs PR #141 — operator's conscious sequencing choice (§0).
