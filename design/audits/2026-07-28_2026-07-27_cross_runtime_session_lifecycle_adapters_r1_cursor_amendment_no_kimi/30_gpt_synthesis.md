# GPT synthesis — Cursor lifecycle amendment

**Target:** `design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`  
**Date:** 2026-07-28  
**Scope:** review-only Cursor amendment; no Antigravity or Kimi  
**Synthesizer:** GPT

## Panel accounting

| Lane | Result |
|---|---|
| DeepSeek V4 Pro | returned, 17,496 tokens |
| Mistral Medium 3.5 | returned, 17,442 tokens |
| MiniMax M3 | returned, 17,036 tokens |
| ByteDance Seed 1.6 | returned, 16,575 tokens |
| Claude Opus CLI | returned |
| Gemini current UI model | failed: response timeout after 180 seconds |
| Perplexity best/sonar | blocked: `cdp_role_busy:chrome_ppl` |
| Standalone Kimi / Perplexity Kimi | omitted by operator boundary |
| Antigravity | not invoked |

The stock paid basket did not fully return. This synthesis is explicitly
partial and does not use a missing lane as evidence of agreement.

## Applied findings

1. Define a Temp-only random nonce mechanism and exact response match without a
   lifecycle schema change.
2. Treat a fired hook with a missed nonce as event-only evidence and a context
   parity failure.
3. Scope identity stability to one surface and conversation; do not compare IDE
   and CLI IDs.
4. Require exactly one canonical registered Git root for full lifecycle state.
5. Reject an unbound `preCompact` before router delegation.
6. Keep the start transcript binding write-once; fail closed on later mismatch.
7. Require two new conversations plus resume/compact evidence before declaring a
   Cursor transcript format stable.
8. Enforce stopped Cursor processes and a final pre-write config re-hash.
9. Record differential causes for a zero-event probe instead of declaring the
   entire host unsupported.
10. Forbid the Cursor `env` output field and derive production time budgets from
    measured Cursor behavior rather than historical Codex values.

These changes are folded into CU0-L, CU1, CU2, the Cursor Definition of Done,
and the engineering review in the target plan.

## Rejected or deferred findings

- The literal GO phrase is an authorization boundary, not a secret credential.
- Historical Codex registry, reaper, emergency-off, and old performance/test
  notes were not demonstrated as blockers for the probe-only Cursor next gate.
- Process pools, async execution, and a universal adapter hierarchy are
  premature before native Cursor evidence exists.
- User-level probe activation, production implementation, and persistent hook
  mutation remain unauthorized by this review.

## Verdict

**CLEAR FOR THE DOCUMENTED CU0-L GATE; PARTIAL PANEL.**

There is no remaining external P1 against the plan's reversible, probe-only next
step after the amendments. This verdict does not grant
`GO CURSOR CU0-L LIVE CONTRACT CAPTURE` and does not approve CU1-CU4 code.
