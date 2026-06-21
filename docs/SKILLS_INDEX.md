# Skills & Commands Index

_Auto-generowane przez `scripts/skills_index.py` — sekcje per-agent czytane na zywo z katalogow skilli; sekcje 2-6 kuratorowane w skrypcie. Nie edytuj recznie sekcji 1._

## 1. Skille per-agent (z katalogow)

### Global — wszystkie agenty (`~/.agents/skills`) — 7
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `minimalist-ui` — Clean editorial-style interfaces.
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).

### Claude Code (`~/.claude/skills`) — 10
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `executor` — Launch the autonomous executor agent.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `master-agent` — Master Agent mode system for structured engineering work.
- `minimalist-ui` — Clean editorial-style interfaces.
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).
- `whatnext` — Steering ritual — answer "what next / co dalej / priorytety / are we drifting" with a STEERING BRIEF grounded in the income north-star, the vision DoD, a cov...

### Codex (`~/.codex/skills`) — 14
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `diagnoze` — Use when the user invokes /diagnoze or /diagnose, reports a bug, regression, broken runtime, failing test, bad replay, flaky behavior, or asks for root-cause...
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
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

### Cursor (`~/.cursor/skills-cursor`) — 25
- `automate` — Use this skill to create Cursor Automations.
- `babysit` — Keep a PR merge-ready by triaging comments, resolving clear conflicts, and fixing CI in a loop.
- `canvas` — A Cursor Canvas is a live React app that the user can open beside the chat.
- `create-hook` — Create Cursor hooks.
- `create-rule` — Create Cursor rules for persistent AI guidance.
- `create-skill` — Create Cursor Agent Skills.
- `create-subagent` — Create custom subagents for specialized AI tasks.
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns.
- `frontend-house-rules` — House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / fronten...
- `gpt-taste` — Elite UX/UI & Advanced GSAP Motion Engineer.
- `image-to-code` — Elite website image-to-code skill for Codex.
- `loop` — Run a prompt or skill in this session on a recurring or variable interval (e.g.
- `migrate-to-skills` — Convert 'Applied intelligently' Cursor rules (.cursor/rules/*.mdc) and slash commands (.cursor/commands/*.md) to Agent Skills format (.cursor/skills/).
- `minimalist-ui` — Clean editorial-style interfaces.
- `redesign-existing-projects` — Upgrades existing websites and apps to premium quality.
- `review` — Review code changes with the Bugbot or Security Review subagent.
- `review-bugbot` — Review code changes with Bugbot subagent.
- `review-security` — Review code changes with Security Review subagent.
- `sdk` — Guide users building apps, scripts, CI pipelines, or automations on top of the Cursor SDK - TypeScript (`@cursor/sdk`) or Python (`cursor-sdk` / `cursor_sdk`).
- `shell` — Runs the rest of a /shell request as a literal shell command.
- `split-to-prs` — Split current work into small reviewable PRs.
- `statusline` — Configure a custom status line in the CLI.
- `tsu-dashboard-taste` — Override for real-time trading/financial dashboards (TSU cockpit, tray panel, live P&L/price/position views).
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

