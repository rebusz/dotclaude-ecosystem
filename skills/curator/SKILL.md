---
name: curator
description: Verify concrete session claims against fresh TruthDeck and repository evidence, then write a fail-closed handoff.
---

# Curator

Use this skill when the operator invokes `/curator` or asks for a verified close of the
current session.

1. Require the exact current session binding from `CLAUDE_SESSION_PLAN_ID`. If it is absent,
   stop with an `UNVERIFIED` result. Never search for a recent scratch file or transcript.
2. Run:

   ```powershell
   python "$env:USERPROFILE\.claude\scripts\curator_claims.py" --session-id "$env:CLAUDE_SESSION_PLAN_ID" --repo "$PWD"
   ```

3. Read the returned JSON once. The `redacted_window` is the only transcript material allowed
   into the model context. Do not reopen the raw transcript.
4. Report the fresh TruthDeck gates, the persisted SessionEnd verdict, the transcript's
   `observed_tail`, and every extracted claim with exactly one state: `VERIFIED`, `REFUTED`, or
   `UNVERIFIED`. Treat claims after the observed tail as absent, never verified.
5. In this same model pass, identify any concrete claim visible in the redacted window that the
   deterministic extractor missed. Add it as `UNVERIFIED` unless the returned repository
   evidence directly proves or refutes it. Do not make a second model call.
6. Return the handoff path from the packet. The handoff is written even when every claim is
   unverified.
7. State whether this session has scratch-file evidence that the router ran. For the
   authoritative merged hook configuration, direct the operator to `/hooks`; do not infer
   wiring from any single configuration source.

The curator never blocks a handoff, never upgrades unknown evidence, never performs a commit,
push, merge, deployment, runtime mutation, or broker/order action.
