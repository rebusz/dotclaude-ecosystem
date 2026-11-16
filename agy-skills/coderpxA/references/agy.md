# Antigravity & Gemini CDP model selection (`/coderpxA`)

Within `/coderpxA`, designate models explicitly by role and task weight:

| Surface / Assignment | Selection | Effort | Router / Selector |
|---|---|---|---|
| **AGY default** (implementation, tests, fixes, routine work) | **Gemini 4 Hydrogen** | `high` | `agy_hydrogen_high` (`gemini-4-hydrogen-high`) |
| **AGY orchestrator** (hard diagnosis, multi-file coupling, plan authoring) | **Orchestrator (Carbon)** | Automatic (omit `--effort`) | `agy_orchestrator_carbon` / `agy_orchestrator_carbon_plan` (`gemini-pro-orchestrator`) |
| **AGY direct Carbon** (plan authoring, hard design/integration when requested directly) | **Gemini 4 Carbon** | `low`, `medium`, or `high` | `agy_carbon_high` / `agy_carbon_plan` (`gemini-4-carbon-high`/`-medium`/`-low`) |
| **AGY Argon** (on demand; non-plan) | **Gemini 4 Argon** | `low`, `medium`, `high`, or `Orchestrator (Argon)` | `agy_argon_high` / `agy_argon_consult` (`gemini-4-argon-*`, `gemini-pro-orchestrator-argon`) |
| **AGY Flash** (fast/low-cost on demand) | **Gemini 3.8 Flash** | `low`, `medium`, or `high` | `agy_flash_high` (`gemini-3.8-flash-*`) |
| **Gemini CDP (`chrome_gemini`:9223)** — Argon (Pro accounts, default/on demand) | **Gemini 4 Argon** | `High` via Thinking level | `argon_cdp` (`--model "Gemini 4 Argon"`) |
| **Gemini CDP (`chrome_gemini`:9223)** — Hydrogen (Pro accounts, on demand; non-plan) | **Gemini 4 Hydrogen** | Picker default or `High` (`Hydrogen High`) | `hydrogen_cdp` (`--model "Gemini 4 Hydrogen"`) |
| **Consultation: Claude Opus 5.5 / Fable** | **Claude Opus 5.5 / Fable** | `high` (read-only `--mode plan --sandbox`) | `agy_opus55_consult` (`claude-opus-5-5-high`) or active Claude Opus/Fable session |
| **Consultation: Astra via Codex** | **GPT-6 Astra (Codex)** | `high` (enforced `-s read-only`, never `xhigh`/`pro`, never `review`/`plan`) | `codex_astra_high` (`gpt-6-astra`) |
| **Sonnet review / grill** | **Claude Sonnet 5.5 (Perplexity CDP)** | Default Perplexity selector (never AGY Sonnet) | `perplexity_sonnet` (`Claude Sonnet 5.5`) |

## Rules
1. **Plan authoring in `/coderpxA`**: permitted **only** with **Carbon on AGY** (`agy_orchestrator_carbon_plan` / `agy_carbon_plan`), invoked with `dispatch.py lane plan --caller coderpxA --prefer-lane <lane_id>`. Non-Carbon workers (`Hydrogen`, `Flash`, `Argon`) and Gemini CDP lanes never author `coderpxA` plans (`NO_PLAN`).
2. **Gemini CDP entitlement & `dszuber` exclusion**: `dszuber` (the only AI Ultra account with Carbon) is **strictly forbidden in Gemini CDP** (ban risk). Allowed CDP accounts are Pro-only and expose **Argon** (`argon_cdp`) and **Hydrogen** (`hydrogen_cdp`) — never Carbon (`WatchF` fails closed on `upsell_` items with `model_not_entitled`).
3. **Consultations**: use `python D:/APPS/_shared/dispatch/dispatch.py lane <diagnose|grill> --prefer-lane <agy_opus55_consult|codex_astra_high> --brief <file>` (or consult an active Claude Opus/Fable session).
4. **Orchestrator effort**: omit `--effort` for `gemini-pro-orchestrator`; record requested effort as automatic and actual effort as unknown unless explicitly reported by the adapter.
5. **Independence**: never route `grill` or `review` to the producer family. Both Gemini-authored diffs and Carbon-authored plans belong to `family: gemini`, so both `grill` and `review` MUST pass `--author-family gemini`.
6. **No AGY Sonnet**: never use AGY Sonnet (`agy_sonnet55_review` / `agy_claude_sonnet` — ~5-minute quota limit); use `perplexity_sonnet` (`Claude Sonnet 5.5`) whenever Sonnet is needed.
