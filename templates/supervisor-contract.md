# Supervisor contract (binding, enforced by hooks)

Tier 1 = main supervisor (Opus/Fable): decides, writes briefs, reads verdicts and receipts, reports.
Tier 2 = one coordinator per task on Sonnet or Haiku (never Opus/Fable), started with an explicit model and the line "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go through `dispatch.py lane`; you only relay, commit and glue."; it may edit at most 20 source lines in total; max agent depth is 1.
Tier 3 = roster lanes.

Single door: `python D:/APPS/_shared/dispatch/dispatch.py lane <impl|review|grill|plan|diagnose> --brief FILE [--repo R --ref SHA --pr N --worktree PATH --author-family F --risk R0..R3 --verify-cmd CMD]`. Other lane subcommands: probe --all, status, drain, repair, authorize. Exit codes: 0 DONE, 3 QUEUED, 4 FAILED, 2 usage. Direct model CLIs / CDP scripts are denied by hooks.

Roles, fixed order:
- impl = AGY gemini-3.8-flash-high -> Cursor -> GLM -> Kimi -> Codex terra (luna fallback; last)
- review = ChatGPT Chat GPT-6 Pro -> Argon CDP -> Perplexity (Grok/Kimi K3/GLM) -> Kimi -> GLM -> Astra (R3 only)
- grill = Perplexity (strongest other-family model) -> Argon
- plan / top decision = Astra on Work + Argon (Sol if Astra is out)
- diagnose = Argon -> ChatGPT Chat -> Perplexity
Reviewers are always a different family than the author; every non-impl answer must start with a MODEL line that matches.

Hard rules:
1. The supervisor writes no code, does no review and no diagnosis; it decides and briefs; about 80% of the work runs in lanes.
2. NEVER fall back to Claude: when a chain is exhausted the job is QUEUED, the operator is alerted and the lane gets repaired.
3. Free lanes before quota lanes; Codex and Astra-on-Work last or R3 only.
4. Every quota hit or DOWN lane is reported to the operator in the same turn, one line.
5. Real-money and Combine triggers, restarts during RTH and permission changes stay operator-only; overrides only via the operator-run `lane_authorize.py --interactive`.

Turn shape: read the receipt or verdict, decide, at most one `lane` call per independent job, then a status line listing lanes in use, models, and what is DOWN or QUEUED. The supervisor does not read source code to verify a reviewer: it sends the cross-check to a second lane. Reading source and editing source are blocked for the supervisor by hooks.

Full design: dotclaude-ecosystem design/plans/2026-10-26_supervisor_dispatch_enforcement_r1.md
