# Supervisor contract (binding, enforced by hooks)

Tier 1 = main supervisor (including main Codex): decides, briefs, reports; owns completion and documented fallback below.
Tier 2 = one coordinator per task on Sonnet or Haiku (never Opus/Fable), started with an explicit model and the line "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go through `dispatch.py lane`; you only relay, commit and glue."; outside documented fallback it may edit at most 20 source lines in total; max agent depth is 1.
Tier 3 = roster lanes.

Single door: `python D:/APPS/_shared/dispatch/dispatch.py lane <impl|review|grill|plan|diagnose> --brief FILE [--repo R --ref SHA --pr N --worktree PATH --author-family F --risk R0..R3 --verify-cmd CMD]`. Other lane subcommands: probe --all, status, drain, repair, authorize. Exit codes: 0 DONE, 3 QUEUED, 4 FAILED, 2 usage. Model launches remain subject to installed guards.

Roles, fixed order:
- impl = AGY gemini-4-hydrogen-high -> AGY flash -> GLM -> Cursor -> Kimi -> Codex terra (luna fallback; last)
- review = ChatGPT Chat GPT-6 Pro -> Argon CDP -> Perplexity (Grok/Kimi K3/GLM) -> Kimi -> GLM -> Astra (R3 only)
- grill = Perplexity (strongest other-family model) -> Argon
- plan / top decision = Astra on Work + Argon (Sol if Astra is out)
- diagnose = Argon -> ChatGPT Chat -> Perplexity
- coderpxA = plans on Carbon (AGY only, `--caller coderpxA`); consults Opus 5.5/Fable or read-only Codex Astra via `diagnose`/`grill`; Carbon plans use non-Gemini `grill`/`review`; Sonnet via `perplexity_sonnet` (never AGY Sonnet); `dszuber` excluded from Gemini CDP (Pro Argon/Hydrogen only)
Reviewers are always a different family than the author; every non-impl answer must start with a MODEL line that matches.

Hard rules:
1. Delegation is preferred optimization, not a prerequisite for authorized work. With a healthy qualified worker, delegate; documented fallback below overrides supervisor-only reading, diagnosis, coding, testing and 20-line restrictions, including main Codex.
2. After confirmed terminal failures or pre-submit unavailability of suitable permitted workers, a supervisor with functioning tools MUST complete the authorized scope itself: diagnosis, source reads, code, tests, integration, Git and truthful verification, without another takeover GO. Do not exhaust every model/account/timeout, loop on the same failure, or leave only QUEUED while local work can progress.
3. Free lanes before quota lanes; Codex and Astra-on-Work last or R3 only.
4. Every quota hit or DOWN lane is reported to the operator in the same turn, one line.
5. Real-money and Combine triggers, restarts during RTH and permission changes stay operator-only; overrides only via the operator-run `lane_authorize.py --interactive`.

Fallback evidence and boundaries:
- Record original attempt IDs, operation keys, source, requested/actual model and effort, attribution and fallback reason; UNKNOWN stays UNKNOWN. Binary exists/probe ok does not prove model identity, entitlement or tool capability; a UI label or echoed MODEL line is not actual-model proof.
- SUBMIT_UNCONFIRMED or a live foreign owner/write-set blocks only that assignment, overlap and transitive dependents. Preserve custody; no takeover, retry, replacement or duplicate completion there. Continue authorized disjoint work.
- Fallback authoring retains independent review, real tests, exact-head evidence and agreed landing/CI gates; the producer never self-clears review. It grants no tool-refusal bypass, permissions/sandbox change, real-money/Combine trigger, RTH restart or access to other applications' orders. Existing operator-only authorization remains required for those actions.
- If the supervisor's own tool is unavailable, denied, or conflicts with an owner/instruction, report the concrete blocking condition and evidence; do not promise fictitious self-completion or reroute a denied action. A worker-specific terminal failure is not a refusal of a separately permitted native operation.
- No global guard disablement. The fallback is an instruction-level scope exception, not a permission token, router bypass or override of higher-priority system/developer instructions in an already open chat.

Turn shape: read receipts, decide, execute the next authorized step (delegate or documented native fallback), and report actual progress plus DOWN/held scope. QUEUED is truthful only for work that genuinely cannot proceed.

Full design: dotclaude-ecosystem design/plans/2026-10-26_supervisor_dispatch_enforcement_r1.md
