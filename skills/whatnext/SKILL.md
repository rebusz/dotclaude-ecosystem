---
name: whatnext
description: >
  Steering ritual — answer "what next / co dalej / priorytety / are we drifting" with a
  STEERING BRIEF grounded in the income north-star, the vision DoD, a coverage/drift map,
  and 2-4 PARALLEL tracks (each priced V0-V10 + routed to an executor). Never invents a
  next step. Use whenever the operator asks what to work on, asks about priorities/drift,
  or wants the big picture — not for executing a single known task.
triggers:
  - /whatnext
---

The operator's core job is **keeping course**: goals + full picture, catching drift,
and not over-focusing on one aspect while equally important ones rot. This skill is that
check. It is **advisory** — it proposes, the operator steers. Never auto-start work,
auto-merge, or touch live/trading state from here (R0/R1 only).

## STEP 1 — Load the steering context (do not skip)

```bash
python ~/.claude/scripts/steer_context.py --cwd "$PWD"
```

Read the `<steer-context>` block it prints. It contains: the **North Star** (income lens),
the **recent-activity** signal, a **coverage map** (DoD aspect × recent activity, with a
confidence note), and the embedded **plan context** (vision Why+DoD / IDEA_BOX / PLANS).

If it prints `insufficient-signal` or a low-confidence note, **honor it**: present gaps as
*candidates to verify*, not facts. The heuristic mis-flags worked aspects whose commits
used different words — a false drift flag actively misdirects steering.

(The same block auto-injects when the operator types a bare "co dalej?" — the
`plan_keyword_detector` UserPromptSubmit hook runs `steer_context` on steering phrases. This
skill is the explicit, richer version of that same ritual.)

## STEP 2 — Produce the STEERING BRIEF

Emit exactly these sections, grounded ONLY in the loaded context (never invent a backlog —
every track must trace to a vision DoD bullet, a PLANS entry, or an IDEA_BOX row):

1. **North-star line.** Restate the goal (live-trading **income**, not hobby) + the single
   nearest milestone toward live (e.g. the PAPER WEEK gate). One line.

2. **Coverage map.** The aspect × activity table from `steer_context`, with the under-served
   aspects flagged. Carry through its confidence note — if low-confidence, say so plainly.

3. **Drift flags.** Aspects with no recent activity (> window) OR an over-focus signal (the
   last several sessions all hit the same 1-2 aspects). Mark confidence.

4. **2-4 parallel tracks**, deliberately spanning **DIFFERENT** aspects so we don't tunnel.
   Each track is a row:

   | aspect | next slice | risk | V | executor |
   |---|---|---|---|---|

   - **risk** = R0 (docs/prompts) · R1 (non-live tooling/tests) · R2 (contracts/persistence
     — plan+GO) · R3 (execution/order path — plan+GO+rollback+validation). LLM agents never
     touch broker API / order path.
   - **V (difficulty V0-V10)** sets the executor — **hard operator rule**:

     | V | task class | executor |
     |---|---|---|
     | V0-V3 | trivial/mechanical: config, docs, format sweeps, single-file edits | Cursor Composer / VS Code OK |
     | V4-V6 | standard implementation, multi-file, routine contracts | Claude Code / Codex |
     | V7-V10 | architecture, core fusion/safety, contract design, judgment-heavy | Claude Code (opus) / careful Codex — **never Composer** |

     **Never give Cursor Composer a task > V3.**

5. **First domino** — one recommended track to start now (usually the income-nearest unblocked
   one) + one sentence why. Weigh every track against the income lens: *does this slice move
   toward live-trading income, or is it polish?* Name it honestly when a track is polish.

6. For each **non-Claude** track (Codex / Composer / VS Code), note that it needs a
   target-ready handoff scoped to that executor's capability before it can be dispatched.

## STEP 3 — Stop. Hand to the operator.

Present the brief and stop. Do **not** begin implementing a track without an explicit GO
(`ok go` / `jedziesz` / `implementuj` / a confirmed plan). R2/R3 tracks additionally need
their own plan + GO + rollback before any code.
