# Antigravity & Gemini CDP model selection (`/coderpxA`)

Within `/coderpxA`, designate models explicitly by role and task weight:

| Surface / Assignment | Selection | Effort | Router / Selector |
|---|---|---|---|
| **AGY default** (implementation, tests, fixes, routine work) | **Gemini 4 Hydrogen** | `high` | `agy_hydrogen_high` (`gemini-4-hydrogen-high`) |
| **AGY orchestrator** (hard diagnosis, multi-file coupling, plan authoring) | **Orchestrator (Carbon)** | Automatic (omit `--effort`) | `agy_orchestrator_carbon` / `agy_orchestrator_carbon_plan` (`gemini-pro-orchestrator`) |
| **AGY direct Carbon** (plan authoring, hard design/integration when requested directly) | **Gemini 4 Carbon** | `low`, `medium`, or `high` | `agy_carbon_high` / `agy_carbon_plan` (`gemini-4-carbon-high`/`-medium`/`-low`) |
| **AGY Argon** (on demand) | **Gemini 4 Argon** | `low`, `medium`, `high`, or `Orchestrator (Argon)` | `agy_argon_high` / `agy_argon_plan` (`gemini-4-argon-*`, `gemini-pro-orchestrator-argon`) |
| **AGY Flash** (fast/low-cost on demand) | **Gemini 3.8 Flash** | `low`, `medium`, or `high` | `agy_flash_high` (`gemini-3.8-flash-*`) |
| **Gemini CDP (`chrome_gemini`:9223)** — Argon (default/on demand) | **Gemini 4 Argon** | `High` via Thinking level | `argon_cdp` (`--model "Gemini 4 Argon"`) |
| **Gemini CDP (`chrome_gemini`:9223)** — Carbon (on demand, incl. plan authoring) | **Gemini 4 Carbon** | Picker default or `High` (`Carbon High`) | `carbon_cdp` (`--model "Gemini 4 Carbon"`) |
| **Gemini CDP (`chrome_gemini`:9223)** — Hydrogen (on demand) | **Gemini 4 Hydrogen** | Picker default or `High` (`Hydrogen High`) | `hydrogen_cdp` (`--model "Gemini 4 Hydrogen"`) |
| **Consultation: Fable / Opus** | **Claude Opus 5.5 / Fable** | `high` (read-only `--mode plan --sandbox`) | `agy_opus55_consult` (`claude-opus-5-5-high`) or active Claude Opus/Fable session |
| **Consultation: Astra via Codex** | **GPT-6 Astra (Codex)** | `high` (never `xhigh`/`pro`, never `review`) | `codex_astra_high` (`gpt-6-astra`) |

## Rules
1. **Plan authoring in `/coderpxA`**: permitted **only** with **Carbon** on AGY (`Orchestrator (Carbon)` or `Gemini 4 Carbon`) or **Carbon** on Gemini CDP (`carbon_cdp`). Hydrogen and Flash worker runs never invent or complete missing plans (`NO_PLAN`).
2. **Consultations**: use `python D:/APPS/_shared/dispatch/dispatch.py lane <plan|diagnose|grill> --prefer-lane <agy_opus55_consult|codex_astra_high> --brief <file>` (or consult an active Claude Opus/Fable session).
3. **Orchestrator effort**: omit `--effort` for `gemini-pro-orchestrator`; record requested effort as automatic and actual effort as unknown unless explicitly reported by the adapter.
4. **Independence**: never route `review` to the producer family (a Gemini-authored change still requires a non-Gemini exact-head reviewer via `--author-family gemini`).
