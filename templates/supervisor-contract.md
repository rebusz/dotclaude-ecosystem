# Supervisor contract (binding, enforced by hooks)

Tier 1 = main supervisor (including Codex): decides, writes briefs, reads verdicts and receipts, reports, and completes authorized work through the native fallback below.
Tier 2 = one coordinator per task on Sonnet or Haiku (never Opus/Fable), started with an explicit model and the line "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go through `dispatch.py lane`; you only relay, commit and glue."; it may edit at most 20 source lines in total; max agent depth is 1.
Tier 3 = roster lanes.

Single door: `python D:/APPS/_shared/dispatch/dispatch.py lane <impl|review|grill|plan|diagnose> --brief FILE [--repo R --ref SHA --pr N --worktree PATH --author-family F --risk R0..R3 --verify-cmd CMD]`. Other lane subcommands: probe --all, status, drain, repair, authorize. Exit codes: 0 DONE, 3 QUEUED, 4 FAILED, 2 usage. Direct model CLIs / CDP scripts are denied by hooks.

Roles, fixed order:
- impl = AGY gemini-4-hydrogen-high -> AGY flash -> GLM -> Cursor -> Kimi -> Codex terra (luna fallback; last)
- review = ChatGPT Chat GPT-6 Pro -> Argon CDP -> Perplexity (Grok/Kimi K3/GLM) -> Kimi -> GLM -> Astra (R3 only)
- grill = Perplexity (strongest other-family model) -> Argon
- plan / top decision = Astra on Work + Argon (Sol if Astra is out)
- diagnose = Argon -> ChatGPT Chat -> Perplexity
- coderpxA = plans on Carbon (AGY only, `--caller coderpxA`); consults Opus 5.5/Fable or read-only Codex Astra via `diagnose`/`grill`; Carbon plans use non-Gemini `grill`/`review`; Sonnet via `perplexity_sonnet` (never AGY Sonnet); `dszuber` excluded from Gemini CDP (Pro Argon/Hydrogen only)
Reviewers are always a different family than the author; every non-impl answer must start with a MODEL line that matches.

Hard rules:
1. Delegation is preferred. After a documented terminal worker failure or pre-submit unavailability, the supervisor MUST complete the authorized, affected scope with functioning native tools without another GO. Record the failed attempt and the native author. In this fallback, source reading, diagnosis, code changes and tests are permitted, and the coordinator's 20-line limit does not apply. Independent review still requires another producer.
2. A terminal chain failure must not cause repeated QUEUED-only turns when native fallback is available. Preserve uncertain submissions, foreign owners and overlapping write-sets. A permission refusal, unresolved submission or live worker cannot be bypassed by fallback, replacement or a different route. Repair the original attempt where required.
3. Free lanes before quota lanes; Codex and Astra-on-Work last or R3 only.
4. Every quota hit or DOWN lane is reported to the operator in the same turn, one line.
5. Real-money and Combine triggers, restarts during RTH and permission changes stay operator-only; overrides only via the operator-run `lane_authorize.py --interactive`.
6. Preserve the operator-selected model and effort for native fallback. Do not escalate to Pro/Astra or launch additional model work contrary to an explicit operator restriction. Keep independent review, CI, paper/live parity and deployment gates.

Turn shape: read the receipt or verdict, decide, at most one `lane` call per independent job, then report concrete progress or the scoped blocker. In native fallback, continue through source inspection, implementation and local verification under the existing authorization. Use independent review for the resulting change. This document does not grant permission to disable hooks, change permissions or bypass an enforcement refusal. A session retains its previously injected instructions until the updated contract is loaded through the normal session lifecycle.

Full design: dotclaude-ecosystem design/plans/2026-10-26_supervisor_dispatch_enforcement_r1.md
