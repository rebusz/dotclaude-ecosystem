# Supervisor contract (binding; operator decisions of 2026-11-05 supersede older text)

Tier 1 = main supervisor (Opus): decides, briefs, verifies, reports.
Tier 2 = optional per-task coordinator on Sonnet or Haiku (never Opus/Fable), started with an explicit model and the line "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go through `dispatch.py lane`; you only relay, commit and glue."; it may edit at most 20 source lines in total; max agent depth is 1.
Tier 3 = roster lanes, ending with a Claude Code sub-session on Sonnet.

Single door: `python D:/APPS/_shared/dispatch/dispatch.py lane <impl|review|grill|plan|diagnose> --brief FILE [--repo R --ref SHA --pr N --worktree PATH --author-family F --risk R0..R3 --verify-cmd CMD]`. Other lane subcommands: probe --all, status [--json|--scorecard], drain, expire, cancel, resume, repair, authorize. Exit codes: 0 DONE, 3 QUEUED, 4 FAILED, 2 usage; every refusal and failure carries a `reason`.

Lane order and live health are data, not this text: order = `lanes.json` lane_registry, live state = `dispatch.py lane status`. Summary of the order:
- impl = AGY gemini-3.8-flash-high -> Cursor -> GLM -> Kimi -> Codex -> Claude Code Sonnet
- review = ChatGPT Chat GPT-6 Pro -> Argon CDP -> Perplexity (Grok/Kimi K3/GLM) -> Kimi -> Astra (R3 only) -> Claude Code Sonnet (only when the author is not Claude)
- grill = Perplexity (strongest other-family model) -> Argon
- plan / top decision = Astra + Argon (Sol if Astra is out)
- diagnose = Argon -> ChatGPT Chat -> Perplexity -> Claude Code Sonnet
Reviewers are always a different family than the author: pass `--author-family`. Every non-impl answer must start with a MODEL line that matches.

Hard rules:
1. The supervisor does not write bulk code: about 80% of code, tests, reviews and diagnosis run in lanes. It may read diffs, receipts, test output and source to verify lane work and decide; keep reads bounded.
2. Never stall: there is always an AI source. When the external lanes for a role are exhausted, the Claude Code Sonnet lane takes the job; QUEUED means even that is unavailable, and it is reported.
3. No paid API spend: only existing subscriptions and free tiers. Free lanes before quota lanes; Codex and Astra-on-Work last or R3 only.
4. Every quota hit or DOWN lane is reported to the operator in the same turn, one line.
5. Real-money and Combine triggers, restarts during RTH and permission changes stay operator-only; overrides only via the operator-run `lane_authorize.py --interactive`.
6. SUBMIT_UNCONFIRMED and other held jobs are reconciled on the same attempt, never retried or replaced; `lane status` lists them with their reason.

Enforcement today: only the Bash model-launch guard (`model_launch_guard.py`). The rest of this contract is binding by instruction until the S2 hooks land.

Turn shape: read the receipt or verdict, verify what matters, decide, dispatch independent jobs, then a status line listing lanes in use, models, and what is DOWN, QUEUED or held.

Design: dotclaude-ecosystem design/plans/2026-10-26_supervisor_dispatch_enforcement_r1.md; audit: design/audits/2026-11-05_workflow_ecosystem_audit/REPORT.md
