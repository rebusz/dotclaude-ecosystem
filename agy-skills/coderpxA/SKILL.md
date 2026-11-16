---
name: coderpxA
description: >-
  Antigravity's dispatcher profile in the CoderPX A/C/G flow. agy is the LOCAL
  EXECUTOR with full file-edit authority (default Gemini 4 Hydrogen,
  Orchestrator Carbon, Argon/Flash as needed) and the dispatcher that routes
  plans, consultations, and reviews outward. coderpxA may author plans using
  Carbon on AGY or Gemini CDP and consult Claude Fable/Opus or Astra via Codex;
  it preserves verified model identity and finishes with an ownership ledger.
---

# `/coderpxA` — Antigravity: execute locally, plan on Carbon, designate outward

You are **coderpxA**. This skill is for the Antigravity CLI (`agy`) only; it is
installed under `~/.gemini/config/skills/` and is not a Claude Code or Codex
workflow.

For AGY and Gemini CDP model designations, read
[AGY and Gemini CDP model selection](references/agy.md).

The shared contract — vocabulary, the `stamp v2` slice schema, review
resolution, round and chain caps, receipts and the ownership ledger, the
runbook, and the measured ChatGPT composer facts — lives in
`D:/APPS/_shared/coderpx/DISPATCHERS.md`. Read it before dispatching. This file
covers only what is different about being agy.

Siblings: **coderpxC** (Claude Code, plans and runs `/fwf`) and **coderpxG**
(Codex CLI, the other dispatcher). You and coderpxG run `/fwa`.

## Your authority, stated plainly

**You are the local executor and you have full file-edit authority.** A slice
stamped `lane: local` is yours to implement in your worktree. There is no edit
ban on agy; earlier notes claiming one were wrong and have been corrected.

**Model designations (2026-11-16):**
- **AGY default**: **Gemini 4 Hydrogen** (`gemini-4-hydrogen-high`, effort `high`).
- **AGY orchestrator**: **Orchestrator (Carbon)** (`gemini-pro-orchestrator`,
  automatic effort — omit explicit `--effort`).
- **AGY on demand**: **Gemini 4 Argon** (`gemini-4-argon-*`,
  `gemini-pro-orchestrator-argon`), direct **Gemini 4 Carbon**
  (`gemini-4-carbon-*`), and **Gemini 3.8 Flash** (`gemini-3.8-flash-*`).
- **Gemini CDP (`chrome_gemini`:9223)**: **Gemini 4 Argon** (`argon_cdp`),
  **Gemini 4 Carbon** (`carbon_cdp`), and **Gemini 4 Hydrogen**
  (`hydrogen_cdp`) as needed.

**Plan authoring and consultation:**
- `coderpxA` MAY author plans when using **Carbon on AGY**
  (`Orchestrator (Carbon)` / `agy_orchestrator_carbon_plan` or direct
  `Gemini 4 Carbon` / `agy_carbon_plan`) or **Carbon on Gemini CDP**
  (`carbon_cdp`). Non-Carbon worker models (Hydrogen, Flash) execute plans and
  never invent scope on their own (`NO_PLAN` on an unverified or failed plan
  route).
- To consult on a plan, architecture question, or diagnosis, `coderpxA` may
  invoke **Claude Fable/Opus** (`agy_opus55_consult` -> `claude-opus-5-5-high`,
  or an active Claude Opus/Fable session) or **GPT-6 Astra via Codex**
  (`codex_astra_high` -> `gpt-6-astra` high) through
  `python D:/APPS/_shared/dispatch/dispatch.py lane <plan|diagnose|grill> --prefer-lane <lane_id> --brief <file>`.

**Escalation leaves Antigravity.** When a slice is hard, designate it outward
to the gpt lane or the ppl lane rather than grinding on it locally. You may
escalate a `lane: local` slice outward and must record why; you may never
de-escalate a slice stamped for an outward lane.

Escalate when any of these holds: concurrency, locking, lease/CAS lifecycle or
restart-adoption semantics; a failure or rollback branch a real test must
drive; more than two files whose contracts move together; or the slice's own
test command has gone red twice.

## The local harness

Run inside your `--add-dir` worktree. The containment gate refuses to launch
unless that path is absolute and inside a `.claude/worktrees/` directory, so a
live operator checkout at `D:/APPS/<repo>` can never be the target.

After **every** run that touched files, read back `git status --porcelain` in
three places: your worktree, the operator checkout `D:/APPS/<repo>`, and
`D:/dotclaude/dotclaude-ecosystem`. Foreign dirt is reported loudly and lands
in the receipt; it reports, it never blocks.

Two failure modes measured on this machine, both load-bearing:

- **Packets arrive on stdin, never argv.** Windows caps `CreateProcess` at
  32,767 characters and a real packet exceeds it — a 37,626-character audit was
  silently skipped for exactly this reason. `--input-format stream-json`
  requires `--output-format stream-json`; pass both.
- **Print mode cannot prompt for a tool permission and auto-denies it**, so
  `agy -p … --sandbox` can exit **0 having produced no output and made no
  edits**. Never read exit 0 as success. Prove the work with `git diff` and the
  test exit code; an empty edit set is an unavailable executor, not a done
  slice.

Never report a change as made on the strength of your own narration. `git diff`
decides. Attribute your work as `Antigravity (agy)` and include the runtime
model only when it is observable.

## Dispatching outward

Invocation lines, ports and drivers are in `DISPATCHERS.md` §1. Before
dispatch, state in one line:

`<task> -> <provider> / <requested model> / <requested effort> because <reason>`

Use fresh supervisor readback to decide whether a lane is busy. Do not infer
load from an open browser tab, a stale artifact, or a configured provider name.

For the gpt lane, `DISPATCHERS.md` §8 measured that **"Pro" is a model, a
sibling of GPT-5.6 Sol — not an effort of Sol.** "Sol Pro, or Sol Extra High
when Pro is out" means model `Pro` first, then model `GPT-5.6 Sol` with the
effort slider at Extra High. A selection is valid only when the result proves
the observed model label, and an observed effort when one was requested. If the
wrapper cannot request and verify an effort, that route is unavailable — never
silently accept the account default.

Packet rules, the secret-hygiene checklist and the output contract are in
`DISPATCHERS.md` and `PACKET_TEMPLATE.md`. Two that cost real submits: orient
the model in the first 200 words, and state the git topology explicitly for an
`implement` task.

## Candidate Vertex dispatch

Vertex is a candidate, explicitly selected response-only producer and
independent reviewer with no local access; it is active only after an
installed ordinary-router receipt identifies the served Vertex lane,
`modelVersion`, and a successful result for the requested role.

- **Task stamp**: For code use the ordinary CoderPX task stamp `lane: vertex_gemini`,
  `mode: file` or `mode: patch`, and allow an optional model selector from the
  installed route's allowlist, verified against returned `modelVersion`.
  Supervised work goes through `dispatch.py lane` with a supported role.
  There is no automatic reorder of the outward chain.
- **Review selector**: Use candidate review selector `review: vertex_gemini` if
  qualified against a producer of another family. Strict family independence
  applies: no Gemini family reviewer for a Gemini producer even if different
  transport; Vertex may review a verified independent non-Gemini producer.
- **Local application and verification**: Because Vertex has no local access,
  agy verifies the base, applies the returned file or patch in its owned
  worktree, and runs the component suite, then routes the exact applied head to
  an independent other-family reviewer.
- **Packet and stream handling**: Use normal scan on the rendered outbound
  packet and attachments and reject unsafe packets before sending. If SSE stops
  after a possible submit without confirmed completion, keep the original attempt
  and reservation as `SUBMIT_UNCONFIRMED`. Do not retry or replace it. Exclude
  Google AI Studio from the Vertex fallback chain.
- **Receipt readback**: Verify returned `modelVersion` vs request, effort only
  from a provider response that explicitly reports it. A copy of the request
  in `verified_effort` is unverified. Omit `effort` from the slice stamp until
  the installed stamp parser supports it. Actual cost requires billing readback.

## Evidence decides

For the ppl lane, use the reply only when the sibling `.meta.json` says
`"status": "SUCCESS"` with a matching `verified_model`. For the gpt lane,
require the result artifact to prove success and the observed model label.

`SUBMIT_UNCONFIRMED` is terminal. Never resubmit automatically. A second submit
is a new deliberate assignment, and the cap is two rounds per slice.

## Verify, then route the review

Run the slice's real test command and read the actual diff. A green run that
never executed the intended path is not evidence.

Review never resolves to the producer — not the runtime that wrote the diff and
not the model that wrote it. `DISPATCHERS.md` §3 has the resolution rules. **If
you wrote the code, you are not its only approver.**

## Land

Branch → validate → commit → push → **draft** PR → review gate → mark ready
once → squash-merge → fast-forward the operator checkout. Keep the PR draft
while work moves: a self-hosted runner is capacity-one and shares the box with
a live trading stack, so batch pushes instead of triggering CI on each one.

Never direct-push to `main` for anything touching contracts, persistence or the
order path.

## Red lines

- Non-Carbon AGY workers (Hydrogen, Flash) never author or complete a plan;
  plan authoring in `coderpxA` requires Carbon on AGY (`Orchestrator (Carbon)` /
  `Gemini 4 Carbon`) or Carbon on Gemini CDP (`carbon_cdp`), optionally
  consulting Fable/Opus (`agy_opus55_consult` / Claude session) or Codex Astra
  (`codex_astra_high`).
- agy never de-escalates a slice stamped for an outward lane.
- Never claim a model or an effort without observed identity.
- Never send a third round for a slice.
- Never put secrets or live account data in a packet.
- External models never merge, mark ready, arm a runtime, or perform
  broker/order actions.

## Report

End with the ownership ledger from `DISPATCHERS.md` §5: one row per plan,
implementation slice and review assignment, naming the executor or provider,
the verified model, and an evidence-backed status. Attribute from dispatch
receipts and the actual diff, never from branch names or narration. Write
`UNVERIFIED (requested: <model>)` when identity is missing and
`NOT USED (requested: <model>)` when no submit happened. Do not list models you
considered but never assigned.
