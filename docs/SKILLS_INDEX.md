# Skills & Commands Index

_Auto-generowane przez `scripts/skills_index.py` — sekcje per-agent czytane na zywo z katalogow skilli; sekcje 2-6 kuratorowane w skrypcie. Nie edytuj recznie sekcji 1._

## 1. Skille per-agent (z katalogow)

### Global — wszystkie agenty (`~/.agents/skills`) — 15
- `codebase-design` — Shared vocabulary for designing deep modules.
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `diagnosing-bugs` — Diagnosis loop for hard bugs and performance regressions.
- `domain-modeling` — Build and sharpen a project's domain model.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `handoff` — Compact the current conversation into a handoff document for another agent to pick up.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `improve-codebase-architecture` — Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
- `minimalist-ui` — Clean editorial-style interfaces.
- `prototype` — Build a throwaway prototype to flesh out a design — a runnable terminal app for state/business-logic questions, or several radically different UI variations...
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `tdd` — Test-driven development.
- `triage` — Move issues and external PRs through a state machine of triage roles — categorise, verify, grill if needed, and write agent-ready briefs.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).

### Claude Code (`~/.claude/skills`) — 73
- `gstack` — Router for the gstack skill suite.
- `autoplan` — Auto-review pipeline — reads the full CEO, design, eng, and DX review skills from disk and runs them sequentially with auto-decisions using 6 decision princi...
- `benchmark` — Performance regression detection using the browse daemon.
- `benchmark-models` — Cross-model benchmark for gstack skills.
- `browse` — Fast headless browser for QA testing and site dogfooding.
- `canary` — Post-deploy canary monitoring.
- `careful` — Safety guardrails for destructive commands.
- `codebase-design` — Shared vocabulary for designing deep modules.
- `codex` — OpenAI Codex CLI wrapper — three modes.
- `context-restore` — Restore working context saved earlier by /context-save.
- `context-save` — Save working context.
- `cso` — Chief Security Officer mode.
- `design-consultation` — Design consultation: understands your product, researches the landscape, proposes a complete design system (aesthetic, typography, color, layout, spacing, mo...
- `design-html` — Design finalization: generates production-quality Pretext-native HTML/CSS.
- `design-review` — Designer's eye QA: finds visual inconsistency, spacing issues, hierarchy problems, AI slop patterns, and slow interactions — then fixes them.
- `design-shotgun` — Design shotgun: generate multiple AI design variants, open a comparison board, collect structured feedback, and iterate.
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `devex-review` — Live developer experience audit.
- `diagnosing-bugs` — Diagnosis loop for hard bugs and performance regressions.
- `diagram` — Turn an English description (or mermaid source) into a diagram triplet: the source, an editable .excalidraw file you can open (gstack)
- `document-generate` — Generate missing documentation from scratch for a feature, module, or entire project.
- `document-release` — Post-ship documentation update.
- `domain-modeling` — Build and sharpen a project's domain model.
- `executor` — Launch the autonomous executor agent.
- `freeze` — Restrict file edits to a specific directory for the session.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `gstack` — Router for the gstack skill suite.
- `gstack-upgrade` — Upgrade gstack to the latest version.
- `guard` — Full safety mode: destructive command warnings + directory-scoped edits.
- `handoff` — Compact the current conversation into a handoff document for another agent to pick up.
- `health` — Code quality dashboard.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `improve-codebase-architecture` — Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
- `investigate` — Systematic debugging with root cause investigation.
- `ios-clean` — Remove the DebugBridge SPM package and all #if DEBUG wiring from an iOS app.
- `ios-design-review` — Visual design audit for iOS apps on real hardware.
- `ios-fix` — Autonomous iOS bug fixer.
- `ios-qa` — Live-device iOS QA for SwiftUI apps.
- `ios-sync` — Regenerate the iOS debug bridge against the latest upstream gstack templates.
- `land-and-deploy` — Land and deploy workflow.
- `landing-report` — Read-only queue dashboard for workspace-aware ship.
- `learn` — Manage project learnings.
- `make-pdf` — Turn any markdown file into a publication-quality PDF.
- `master-agent` — Master Agent mode system for structured engineering work.
- `minimalist-ui` — Clean editorial-style interfaces.
- `office-hours` — YC Office Hours — two modes.
- `open-gstack-browser` — Launch GStack Browser — AI-controlled Chromium with the sidebar extension baked in.
- `pair-agent` — Pair a remote AI agent with your browser.
- `plan-ceo-review` — CEO/founder-mode plan review.
- `plan-design-review` — Designer's eye plan review — interactive, like CEO and Eng review.
- `plan-devex-review` — Interactive developer experience plan review.
- `plan-eng-review` — Eng manager-mode plan review.
- `plan-tune` — Self-tuning question sensitivity + developer psychographic for gstack (v1: observational).
- `prototype` — Build a throwaway prototype to flesh out a design — a runnable terminal app for state/business-logic questions, or several radically different UI variations...
- `qa` — Systematically QA test a web application and fix bugs found.
- `qa-only` — Report-only QA testing.
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `retro` — Weekly engineering retrospective.
- `review` — Pre-landing PR review.
- `scrape` — Pull data from a web page.
- `setup-browser-cookies` — Import cookies from your real Chromium browser into the headless browse session.
- `setup-deploy` — Configure deployment settings for /land-and-deploy.
- `setup-gbrain` — Set up gbrain for this coding agent: install the CLI, initialize a local PGLite or Supabase brain, register MCP, capture per-remote trust policy.
- `ship` — Ship workflow: detect + merge base branch, run tests, review diff, bump VERSION, update CHANGELOG, commit, push, create PR.
- `skillify` — Codify the most recent successful /scrape flow into a permanent browser-skill on disk.
- `spec` — Turn vague intent into a precise, executable spec in five phases.
- `sync-gbrain` — Keep gbrain current with this repo's code and refresh agent search guidance in CLAUDE.md.
- `tdd` — Test-driven development.
- `triage` — Move issues and external PRs through a state machine of triage roles — categorise, verify, grill if needed, and write agent-ready briefs.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).
- `unfreeze` — Clear the freeze boundary set by /freeze, allowing edits to all directories again.
- `whatnext` — Steering ritual — answer "what next / co dalej / priorytety / are we drifting" with a STEERING BRIEF grounded in the income north-star, the vision DoD, a cov...

### Codex (`~/.codex/skills`) — 70
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `diagnoze` — Use when the user invokes /diagnoze or /diagnose, reports a bug, regression, broken runtime, failing test, bad replay, flaky behavior, or asks for root-cause...
- `domain-modeling` — Build and sharpen a repo's shared domain language.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `grill-me` — Stress-test a plan, design, slice, PRD, or architecture proposal before implementation.
- `gstack` — Fast headless browser for QA testing and site dogfooding.
- `autoplan` — Auto-review pipeline — reads the full CEO, design, eng, and DX review skills from disk and runs them sequentially with auto-decisions using 6 decision princi...
- `benchmark` — Performance regression detection using the browse daemon.
- `benchmark-models` — Cross-model benchmark for gstack skills.
- `browse` — Fast headless browser for QA testing and site dogfooding.
- `canary` — Post-deploy canary monitoring.
- `careful` — Safety guardrails for destructive commands.
- `claude` — Claude Code CLI wrapper for non-Claude hosts - three modes.
- `context-restore` — Restore working context saved earlier by /context-save.
- `context-save` — Save working context.
- `cso` — Chief Security Officer mode.
- `design-consultation` — Design consultation: understands your product, researches the landscape, proposes a complete design system (aesthetic, typography, color, layout, spacing, mo...
- `design-html` — Design finalization: generates production-quality Pretext-native HTML/CSS.
- `design-review` — Designer's eye QA: finds visual inconsistency, spacing issues, hierarchy problems, AI slop patterns, and slow interactions — then fixes them.
- `design-shotgun` — Design shotgun: generate multiple AI design variants, open a comparison board, collect structured feedback, and iterate.
- `devex-review` — Live developer experience audit.
- `diagram` — Turn an English description (or mermaid source) into a diagram triplet: the source, an editable .excalidraw file you can open on excalidraw.com, and rendered...
- `document-generate` — Generate missing documentation from scratch for a feature, module, or entire project.
- `document-release` — Post-ship documentation update.
- `freeze` — Restrict file edits to a specific directory for the session.
- `guard` — Full safety mode: destructive command warnings + directory-scoped edits.
- `health` — Code quality dashboard.
- `investigate` — Systematic debugging with root cause investigation.
- `ios-clean` — Remove the DebugBridge SPM package and all #if DEBUG wiring from an iOS app.
- `ios-design-review` — Visual design audit for iOS apps on real hardware.
- `ios-fix` — Autonomous iOS bug fixer.
- `ios-qa` — Live-device iOS QA for SwiftUI apps.
- `ios-sync` — Regenerate the iOS debug bridge against the latest upstream gstack templates.
- `land-and-deploy` — Land and deploy workflow.
- `landing-report` — Read-only queue dashboard for workspace-aware ship.
- `learn` — Manage project learnings.
- `make-pdf` — Turn any markdown file into a publication-quality PDF.
- `office-hours` — YC Office Hours — two modes.
- `open-gstack-browser` — Launch GStack Browser — AI-controlled Chromium with the sidebar extension baked in.
- `pair-agent` — Pair a remote AI agent with your browser.
- `plan-ceo-review` — CEO/founder-mode plan review.
- `plan-design-review` — Designer's eye plan review — interactive, like CEO and Eng review.
- `plan-devex-review` — Interactive developer experience plan review.
- `plan-eng-review` — Eng manager-mode plan review.
- `plan-tune` — Self-tuning question sensitivity + developer psychographic for gstack (v1: observational).
- `qa` — Systematically QA test a web application and fix bugs found.
- `qa-only` — Report-only QA testing.
- `retro` — Weekly engineering retrospective.
- `review` — Pre-landing PR review.
- `scrape` — Pull data from a web page.
- `setup-browser-cookies` — Import cookies from your real Chromium browser into the headless browse session.
- `setup-deploy` — Configure deployment settings for /land-and-deploy.
- `setup-gbrain` — Set up gbrain for this coding agent: install the CLI, initialize a local PGLite or Supabase brain, register MCP, capture per-remote trust policy.
- `ship` — Ship workflow: detect + merge base branch, run tests, review diff, bump VERSION, update CHANGELOG, commit, push, create PR.
- `skillify` — Codify the most recent successful /scrape flow into a permanent browser-skill on disk.
- `spec` — Turn vague intent into a precise, executable spec in five phases.
- `sync-gbrain` — Keep gbrain current with this repo's code and refresh agent search guidance in CLAUDE.md.
- `unfreeze` — Clear the freeze boundary set by /freeze, allowing edits to all directories again.
- `gstack-upgrade` — Upgrade gstack to the latest version.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `improve` — Use when the user invokes /improve, asks for architecture improvement, refactoring opportunities, deeper modules, better test seams, or codebase AI-navigabil...
- `master-agent` — Route Codex mode commands through the canonical dszub master-agent protocol.
- `minimalist-ui` — Clean editorial-style interfaces.
- `prototype` — Use when the user invokes /prototype, wants a throwaway logic/UI experiment, wants to feel out a state model, compare UI variants, or sanity-check an idea be...
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `tdd` — Use when the user invokes /tdd, asks for test-driven development, wants a behavior implemented test-first, or a bug fixed by writing the regression test befo...
- `tester` — Supervisor-led test automation for Tsignal and related Windows runtime flows.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).
- `zoom-out` — Use when the user invokes /zoom-out, asks for broader context, wants to understand a module/path/repo before acting, or seems lost in implementation details.

### Cursor (`~/.cursor/skills-cursor`) — 18
- `automate` — Use this skill to create Cursor Automations.
- `babysit` — Keep a PR merge-ready by triaging comments, resolving clear conflicts, and fixing CI in a loop.
- `canvas` — A Cursor Canvas is a live React app that the user can open beside the chat.
- `create-hook` — Create Cursor hooks.
- `create-rule` — Create Cursor rules for persistent AI guidance.
- `create-skill` — Create Cursor Agent Skills.
- `create-subagent` — Create custom subagents for specialized AI tasks.
- `loop` — Run a prompt or skill in this session on a recurring or variable interval (e.g.
- `migrate-to-skills` — Convert 'Applied intelligently' Cursor rules (.cursor/rules/*.mdc) and slash commands (.cursor/commands/*.md) to Agent Skills format (.cursor/skills/).
- `review` — Review code changes with the Bugbot or Security Review subagent.
- `review-bugbot` — Review code changes with Bugbot subagent.
- `review-security` — Review code changes with Security Review subagent.
- `sdk` — Guide users building apps, scripts, CI pipelines, or automations on top of the Cursor SDK - TypeScript (`@cursor/sdk`) or Python (`cursor-sdk` / `cursor_sdk`).
- `shell` — Runs the rest of a /shell request as a literal shell command.
- `split-to-prs` — Split current work into small reviewable PRs.
- `statusline` — Configure a custom status line in the CLI.
- `update-cli-config` — View and modify Cursor CLI configuration settings in ~/.cursor/cli-config.json.
- `update-cursor-settings` — Modify Cursor/VSCode user settings in settings.json.

## 2. System "mode" (master-agent) — `mode <X> task ...` / `tryb <X>`
- **Core:** OPERATOR, ARCHITECT, IMPLEMENT, DEBUG, INVESTIGATE, AUDIT, AUDIT_AI, REVIEW, TEST, CONTRACT, INTEGRATE, QUANT, POSTMORTEM
- **Ops:** SHIP, QA, CSO, OFFICE-HOURS, AUTOPLAN, RETRO, CAREFUL, LEARN
- **gstack aliasy:** /review /ship /qa /investigate /cso /retro /learn /office-hours /autoplan /careful /plan-ceo-review /plan-eng-review /executor

## 3. Multi-model audyt & fusion
- `/fusion` — presety cheap / breadth / quality / matrix / matrixP
- `mode auditF` (free lanes) - `mode auditP` (paid) - auditQ/auditAI (aliasy)

## 4. Planowanie, research, pamiec
- whatnext - plans - deep-research - executor
- claude-mem: make-plan - do - mem-search - smart-explore - timeline-report

## 5. Claude Code — wbudowane workflow commands
code-review - simplify - verify - run - init - review - security-review - loop - schedule - update-config - keybindings-help - fewer-permission-prompts - claude-api

## 6. Dokumenty / kreatywne (anthropic-skills)
docx - pdf - pptx - xlsx - algorithmic-art - skill-creator - consolidate-memory - setup-cowork

> Komendy z dialogiem terminala (/permissions, /config, /agents, /doctor, /hooks) dzialaja tylko w interaktywnym `claude`, nie w sesji nieinteraktywnej.

