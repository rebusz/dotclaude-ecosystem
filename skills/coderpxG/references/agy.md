# Antigravity model selection

Within CoderPX G, choose the AGY model when assigning a new task.

| Assignment | AGY / Gemini CDP selection | Effort |
|---|---|---|
| Hard diagnosis, coupled changes, difficult integration, or coderpxA plan authoring | Orchestrator (Carbon) | Let the orchestrator choose automatically. Omit an explicit effort override. |
| Default implementation, testing, review, or research assigned to AGY | Gemini 4 Hydrogen | Select High explicitly (`gemini-4-hydrogen-high`). |
| Direct Gemini 4 Carbon requested (or coderpxA plan authoring) | Gemini 4 Carbon | Use the requested level (`low`, `medium`, `high`) on AGY or `carbon_cdp` on Gemini CDP. |
| On-demand AGY Argon or Flash | Gemini 4 Argon / Gemini 3.8 Flash | Use requested `gemini-4-argon-*` (`gemini-pro-orchestrator-argon`) or `gemini-3.8-flash-*`. |
| Gemini CDP (`chrome_gemini`:9223) on demand | Argon (`argon_cdp`), Carbon (`carbon_cdp`), Hydrogen (`hydrogen_cdp`) | `Argon` at `High`; `Carbon`/`Hydrogen` as needed. |

Use the existing CoderPX dispatcher and verify the native model identity in the receipt. The Hydrogen High selector is `gemini-4-hydrogen-high`. For the orchestrated route, verify that the installed selector maps to **Orchestrator (Carbon)**. For `coderpxA` plan/architecture consultation, `agy_opus55_consult` (Opus 5.5) and `codex_astra_high` (Astra on Codex) are also available via `dispatch.py lane`. The direct Carbon and Orchestrator (Argon) selections are distinct. When the orchestrator does not report its internal effort, record requested effort as automatic and actual effort as unknown. Preserve the model and owner of work already submitted and the normal independent-review rules.
