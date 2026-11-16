# Antigravity model selection

Within CoderPX G, choose the AGY model when assigning a new task.

| Assignment | AGY / Gemini CDP selection | Effort |
|---|---|---|
| Hard diagnosis, coupled changes, difficult integration, or coderpxA plan authoring | Orchestrator (Carbon) | Let the orchestrator choose automatically. Omit an explicit effort override. |
| Default implementation, testing, review, or research assigned to AGY | Gemini 4 Hydrogen | Select High explicitly (`gemini-4-hydrogen-high`). |
| Direct Gemini 4 Carbon requested (or coderpxA plan authoring) | Gemini 4 Carbon | Use the requested level (`low`, `medium`, `high`) on AGY (Carbon is not entitled in Pro Gemini CDP). |
| On-demand AGY Argon or Flash | Gemini 4 Argon / Gemini 3.8 Flash | Use requested `gemini-4-argon-*` (`gemini-pro-orchestrator-argon`) or `gemini-3.8-flash-*`. |
| Gemini CDP (`chrome_gemini`:9223) on demand (Pro accounts only; never `dszuber`) | Argon (`argon_cdp`), Hydrogen (`hydrogen_cdp`, non-plan) | `Argon` at `High`; `Hydrogen` as needed. |

For the full `/coderpxA` selector table, see [AGY and Gemini CDP model selection](../../../agy-skills/coderpxA/references/agy.md). Key rules: Hydrogen High is `gemini-4-hydrogen-high`; Orchestrator (Carbon) omits `--effort`; `coderpxA` plans use only Carbon on AGY (`--caller coderpxA`), with non-Gemini `grill`/`review` (`--author-family gemini`); `dszuber` is strictly excluded from Gemini CDP; consultations (`diagnose`/`grill`) may use `agy_opus55_consult` or read-only `codex_astra_high`; use `perplexity_sonnet` instead of AGY Sonnet (~5-minute quota).
