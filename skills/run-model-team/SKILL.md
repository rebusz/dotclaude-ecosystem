---
name: run-model-team
description: "Orchestrate parallel repository work from a GPT-5.6 Sol supervisor using ChatGPT CDP, Ox Alpha through OpenCode, Antigravity, local Qwen3.8, task-routed Perplexity CDP models, and critical-only Claude Fable 5 advice. Use for /model-team and parallel model delegation. Kimi CLI is retired (the Kimi 3 Perplexity picker route stays live); Cursor is disabled through 2026-09-08."
---

# Run Model Team

Sol supervises and accepts work; it is not the default code writer. Keep the
approved plan separate from the run queue. The plan owns scope and gates. The
queue owns exact workers, worktrees, write-sets, dependencies, evidence, and
status.

## Active roster

| Lane | Normal role | Boundary |
|---|---|---|
| Sol (`gpt-5.6-sol`, high) | Supervisor, task carving, synthesis, conflict resolution, final acceptance | Read-only over worker code |
| ChatGPT `chrome_gpt` CDP | Primary GPT coding lane, especially one-file and bounded semantic changes | Required for coding/review/audit; use `cdp_chatgpt_code.py`, one target file per run; no Codex CLI fallback |
| Ox Alpha via OpenCode | Co-primary worker for fresh modules, bounded edits, test scaffolds, and architecture experiments | Exact model `opencode/x-preview-f-free`; R2/R3 output is a draft until independently re-derived and tested |
| Antigravity CLI | High-throughput bounded implementation, repetitive changes, and test expansion | Exact model `gemini-3.7-flash-high`; isolated worktree; authenticated model proof required |
| Local Qwen3.8-27B | Offline long-context code generation, test ideas, mechanical draft patches, and overnight assistance | `127.0.0.1:8080`; default model-team use is no-tools/codegen only, never direct GitHub mutation |
| Perplexity CDP models | Current research, adversarial questions, independent design/quant viewpoints, and exact-head review support | Supervisor owns `chrome_ppl`; probe the live picker and assign different bounded questions to suitable visible models |
| Claude Fable 5 CLI | Additional judgment for genuinely important architecture, quant, or design decisions | Critical-only advisory lane; never routine coding or default review |

### Retired and paused lanes

- **Kimi CLI is retired.** Do not probe, dispatch, list, or silently substitute it.
  This retirement is scoped to the standalone **CLI lane** only. The **Kimi 3
  route through the Perplexity picker is live** (`chrome_ppl` 9224, see
  `D:/APPS/_shared/PORTS.md`) and is a valid strong model for plans and reviews
  via CoderPX. Do not read "Kimi is retired" as covering it.
- **Cursor is OFF through 2026-09-08.** Do not probe or dispatch it before that
  date. On or after 2026-09-08 it remains disabled until the operator explicitly
  re-enables it and a fresh exact-model/auth/workspace preflight passes.

Do not silently substitute models. A binary, version string, stale browser tab,
or successful process exit is not model readiness. Record unavailable,
unauthenticated, timed-out, malformed, stale-head, or model-mismatched lanes as
blocked.

## Task routing

Use dependencies and file ownership before provider preference.

- Broad or difficult implementation: ChatGPT, Ox, or Antigravity carry the
  aggregate work.
- Existing-file semantic changes: prefer ChatGPT. Ox may take one
  precisely specified semantic change when the supervisor already knows the
  target structure.
- Fresh modules, bounded experiments, mechanical tests: prefer Ox or
  Antigravity.
- Offline draft/codegen and long prompts without direct writes: use local
  Qwen3.8, then hand the result to a real worktree writer.
- Current research or cross-model challenge: use Perplexity CDP. Probe the live
  picker first; do not hardcode stale UI labels. Give each selected model a
  distinct question rather than asking a swarm the same generic prompt.
- Very important architecture, quant, or design: Sol may add one Fable 5 pass,
  then synthesize it with repo evidence and other independent results. Fable is
  optional, quota-conscious, and never an implementation authority.

Starting load weights, adjusted for readiness and dependencies:

```text
chatgpt=5, ox=4, antigravity=4, qwen=2-codegen
perplexity=task-routed-advisory, fable=critical-only
```

No worker reviews its own diff. Provider prose is never implementation or test
evidence.

## Invocation and workflow ownership

Accept `$run-model-team <task>` or `/model-team <task>`.

- Default lifecycle is `/fwf <authoritative-plan>`.
- Use `/fwp` only when the operator explicitly requests paid routing.
- Reuse and amend an overlapping authoritative plan; never create a competing
  R1/R2/R3 plan.
- A valid standing GO covers only that plan's approved implementation and
  landing lifecycle. Real-money/Combine triggers, broker submit/modify/cancel,
  production deployment, destructive actions, and scope expansion retain
  separate just-in-time gates.

The owning `/fwf` or `/fwp` workflow owns plan review, implementation review,
in-scope repairs, PR, CI, merge, and checkout synchronization. Model-team is the
worker pool inside that lifecycle, not an alternate review or landing route.

## Preflight

1. Resolve the repo, read its `AGENTS.md`/`CLAUDE.md`, and load plan context.
2. Preserve dirty/owned checkouts. Each direct writer gets an isolated worktree
   and an exclusive file allowlist.
3. Run the canonical dispatcher by absolute path:

   ```powershell
   python "C:/Users/dszub/.codex/skills/run-model-team/scripts/model_team.py" doctor --deep
   ```

4. Dispatch only roles reported ready for the intended capability. Treat
   `JIT_CRITICAL_ONLY` Fable as unavailable for ordinary work.
5. For Perplexity, use live `chrome_ppl` picker evidence. Do not ask the operator
   to inspect or control the hidden CDP session.
6. Do not start local Qwen merely to improve roster size. If it is offline,
   report it blocked unless the current task explicitly authorizes starting that
   local inference service.

## Provider contracts

### ChatGPT

Use the existing ChatGPT CDP driver. Coding, audit, and review must fail closed
when `chrome_gpt` is unavailable; Codex CLI is not a fallback:

```powershell
python D:/APPS/WatchF/scripts/cdp_chatgpt_code.py `
  --prompt-file <packet> --write <repo-relative-target> `
  --repo-root <isolated-worktree> --include-current <file> `
  --require-single --out <result.json>
```

The CDP driver owns one target file. Split multi-file work by exclusive file or
route it to another worker. Verify the real diff and tests after every run.

### Ox Alpha / OpenCode

Read `D:/APPS/_shared/opencode/README.md` before first use in a session. Pin
`opencode/x-preview-f-free`, pass the packet on stdin, and set `--dir` to an
isolated worktree. Keep packets near or below 8 KB, one semantic change per run,
and paste known facts instead of asking for repo-wide discovery. A confident
Ox reply over a byte-identical file is a known failure mode; diff plus tests are
mandatory.

### Antigravity

Require host-context `agy models` to contain `gemini-3.7-flash-high`. Dispatch
with high effort, `accept-edits`, sandbox, stream JSON, and a dedicated
worktree. Never use `--dangerously-skip-permissions`. Preserve raw
`RESOURCE_EXHAUSTED` evidence without guessing its cause.

### Local Qwen3.8

Read `D:/APPS/_shared/PORTS.md` and the current Qwen handoff before relying on
it. Probe `/health` and `/v1/models` at `127.0.0.1:8080`. Model-team defaults
to no-tools HTTP codegen: Qwen returns a draft artifact, while a worktree writer
applies and tests it. Its server-side GitHub MCP write lifecycle is outside the
default model-team boundary.

### Perplexity CoderPX CDP

Use `D:/APPS/WatchF/scripts/coderpx.py --probe-models` for the current
picker. **Visible is not selectable.** Entries above the subscription tier
render greyed out with a padlock but still appear in a scraped listing — as of
2026-08-27 that is `GPT-5.6 Sol Max` and `Claude Opus 5 Max`. Never dispatch to
either; the usable GPT variant here is `GPT-5.6 Terra`, and `Sol` is the
ChatGPT lane (`chrome_x`), not Perplexity. Selectable on 2026-08-27: `Sonar 2`,
`GPT-5.6 Terra`, `Gemini 3.7 Flash`, `Claude Sonnet 5`, `Kimi K3`, `GLM 5.2`,
`Grok 4.6`, `Nemotron 3 Ultra`. Then dispatch a fully rendered
`coderpx.packet.v2` packet through
`D:/APPS/WatchF/scripts/coderpx.py --model <visible-model-fragment>`. CoderPX
owns the Conductor + on-demand `chrome_ppl` lifecycle and writes response plus
manifest artifacts. A failed picker, nonzero exit, missing/partial manifest,
timeout, or rejected response is `NO_RESULT`, never PASS. Implementation tasks
require an isolated worktree. Perplexity may create only the packet-authorized
draft branch/PR through its connector; it never marks Ready or merges.

### Fable 5

Use Claude CLI non-interactively with model alias `fable`, max effort, plan/no-
tools posture, and no session persistence. The dispatcher refuses Fable unless
`--critical` and `--task-kind architecture|quant|design` are both present.
Fable advises; Sol decides from evidence.

## Queue and dispatch

Before dispatch, materialize one run-specific `queue.json` in OS temp:

| Task | Owner | Worktree | Files | Dependencies | Validation | Status |
|---|---|---|---|---|---|---|

Every task records `id`, `owner`, `status`, `depends_on`, `repo`,
`worktree`, `scope`, `acceptance`, `commit_sha`, and `review`. Allowed
statuses are `blocked`, `ready`, `running`, `implemented`, `validated`,
`reviewed`, and `landed`. At most one task owns a file or hidden runtime
resource.

Examples:

```powershell
python <dispatcher> run --role antigravity --repo <worktree> --prompt-file <packet> --out <result>
python <dispatcher> run --role ox --repo <worktree> --prompt-file <packet> --out <result>
python <dispatcher> run --role chatgpt --repo <worktree> --prompt-file <packet> --target-file <relative-file> --out <result.json>
python <dispatcher> run --role qwen --repo <repo> --prompt-file <packet> --out <draft.md>
python <dispatcher> run --role perplexity --repo <isolated-worktree> --prompt-file <coderpx.packet.v2> --provider-model <live-picker-fragment> --out <result.md>
python <dispatcher> run --role fable --repo <repo> --prompt-file <packet> --task-kind architecture --critical --out <result.json>
```

Workers may edit and test only inside their packet. The sole commit/push
exception is a packet-authorized CoderPX implementation branch plus Draft PR;
no worker merges, marks Ready, restarts runtimes, or triggers external/live
effects. Sol or the owning workflow inspects the real diff and test exit code
before accepting anything.

## Review and closeout

Use the exact-head review stage owned by `/fwf` or `/fwp`. An in-team reviewer
must be ready, independent, and not the author. Perplexity and Fable findings
are advisory inputs; they do not replace real-path tests or exact-head diff
review.

After every ship-blocking repair: validate, commit, push the corrected head, and
review that exact head again. Final reporting separates implementation,
validation, review, PR/merge state, and runtime/broker proof, and includes the
queue plus every provider result or blocking artifact.
