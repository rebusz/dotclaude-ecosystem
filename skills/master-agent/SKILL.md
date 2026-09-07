---
name: master-agent
description: Route explicit mode or tryb requests and ordered mode chains to engineering protocols. Use for /fwf and /fwp lifecycle requests. Discussing or auditing a command's text does not invoke that command.
---

# Master Agent — engineering mode router

Parse `mode <MODE> [MODE2 ...] task <description>` and its explicit Polish
`tryb` equivalent. Accept omitted `task` when intent is clear. Preserve mode
order and each mode's output/closing tag. A command mentioned as the subject
of analysis is data, not an instruction to run it.

`go` confirms an already understood scope. Preserve it through in-scope fixes,
corrected heads, review, CI and landing. It does not grant an unknown scope,
live trigger or fresh review evidence. Do not repeat a settled approval.

## Before a mode

For plan creation/review/execution, run the existing plan_context_loader.py
pre-step before other task tools. Read repo instructions, Why/DoD and related
active plans. Prefer amending the owner plan. Record actual repo/worktree/head,
foreign changes and risk of the proposed effect separately from writing docs.

Read [the evidence contract](references/protocols/00-contract.md) once, then the
requested role only. If Prompts/master_agent.md exists in the repo, read its
matching section and preserve its domain/output requirements. Resolve conflicts
through actual instruction hierarchy and current operator authority; never
silently drop a repo contract or revive a superseded GO restriction. Installing
a global fallback is not migration of every repo-local mode file.

## Role selection

| Mode | Protocol | Closing tag |
|---|---|---|
| AUDIT | [audit](references/protocols/audit.md) | `>> AUDIT COMPLETE` |
| ARCHITECT | [architect](references/protocols/architect.md) | `>> ARCHITECTURE COMPLETE` |
| QUANT | [quant](references/protocols/quant.md) | `>> QUANT COMPLETE` |
| DEBUG | [debug](references/protocols/debug.md) | `>> DEBUG COMPLETE` |
| INVESTIGATE | Same [debug](references/protocols/debug.md) body | `>> INVESTIGATION COMPLETE` |
| IMPLEMENT | [implement](references/protocols/implement.md) | `>> DONE` only after scoped delivery |

Diagnosis aliases share one body; do not start a second loop. The standalone
/diagnoze adapter still needs its source updated before claiming this alias is
installed. For other modes read only the requested section of
[the retained mode reference](refs/legacy-modes.md), or the installed named
gstack skill. Missing sections must be reported with the checked paths before
a bounded fallback; do not invent a protocol.

CEO, independent plan audit, synthesis, engineering and implementation review
remain distinct [workflow roles](references/protocols/README.md). Their v2
transport integration is a coordinated change: never place the new audit role
under a legacy TOP 3 wrapper or claim its parser changed by reading a file.

## Review Workflow Routing
This table is the authoritative router for plan and implementation review. Other
skills and global rules must reference it instead of restating their own routing.

| Risk | Full workflow route | Question / approval policy |
|---|---|---|
| R3 | `/fwf` or `/fwp`: CEO -> unified audit -> eng -> implementation -> review | CEO product/risk questions go to operator; one standing GO before implementation |
| R2 | `/fwf` or `/fwp`: CEO -> unified audit -> eng -> implementation -> review | CEO and eng questions auto-resolved; one standing GO before implementation |
| R1 | `/fwf` or `/fwp`: CEO -> unified audit -> eng -> implementation -> review | CEO and eng questions auto-resolved; no implementation GO |
| R0 | No mandatory full workflow | Proceed normally |

`/fwf` uses the OpenRouter-free basket; `/fwp` uses the paid OpenRouter
complement basket. R1/R2/R3 and both clients use one fixed panel: ChatGPT CDP
(only GPT-5.6 Sol: Pro effort with a safe same-model pre-submit xhigh fallback), Antigravity
`gemini-3.7-flash-high` (Gemini CDP `gemini-3.7-flash` fallback), and Perplexity GLM 5.3/Kimi 3/Grok 4.6/Sonnet 5/GPT
Terra. Claude CLI, Codex CLI, standalone GLM CLI, and nested CLI tournament
synthesis are excluded. The selected command owns the entire
lifecycle through exact-head `review`, in-scope fixes, PR-ready, CI, merge, and
checkout synchronization. There is no separate closeout command.

The unified `fuse.py` Python runner is an internal stage, not a public workflow
entrypoint. It exposes only `--mode free|paid`; model presets, lane selection,
and CDP bypasses are not part of the workflow contract. Codex passes
`--synthesizer gpt`; Claude Code passes `--synthesizer claude`; this records the
final judge and never changes the fixed panel.

## Host entry and delivery

Resolve the current host's installed command: Claude uses
~/.claude/commands/{fwf,fwp}.md; Codex uses ~/.codex/prompts/{fwf,fwp}.md.
Read that whole command and return each stage's result to its owner. Do not
recursively invoke /fwf, create another closeout command or a second tournament.
The candidate full-workflow reference is a migration design until its adapters
are installed; it does not replace the active command by assertion.
The maintained [host adapter sources](references/host-adapters/README.md) and
[dispatch handoff](references/protocols/workflow-dispatch.md) define that release
boundary. Load the handoff when running a full workflow, not for a mode-only task.

Astra authors prompt design, plans and key decisions. Configured CDP lanes
author substantive implementation and independent review. Local Codex extracts
context, applies, tests and handles Git; failed CDP is not a local authoring
exception. Preserve actual stamp-v2 ownership, dispatcher dry-run, Conductor
admission, attempt caps and terminal uncertain-submit behavior. Do not invent
receipt fields, model routes, resource leases or retry credit in prompt text.

Risk scales care, not code access. Live read remains available. Real-money or
Combine triggers, production deploy and destructive actions keep their distinct
just-in-time authority. Source drafts are not installed or runtime evidence.

Zero findings is valid. Keep missing context, failed tests and unavailable or
stale review visible. Consensus and exit zero alone do not grant clearance.
Reviewers must be independent of the producer and assess actual current source
with required attestation. Preserve configured gates, never invent quorum.

ARCHITECT's Ponytail checkpoint remains only for concrete R0/R1 simplification
under its current skill, never for audit, QUANT, R2/R3 or live-path work. After
plan changes run plan_context_updater.py on the owner plan. Retain the required
EPILOG_PAYLOAD: start_sha, end_sha, plan_path, committed, resolved_ideas.
Complete the authorized lifecycle while preserving foreign changes; stop only
at a real unresolved boundary or failed prerequisite.
