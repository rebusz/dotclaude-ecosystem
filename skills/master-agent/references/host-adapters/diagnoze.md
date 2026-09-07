---
name: diagnoze
description: Diagnose a bug, broken runtime or regression with a fast feedback loop. Handles /diagnoze and /diagnose using the shared DEBUG protocol.
---

# Diagnose

Resolve the installed protocol library: `~/.codex/skills/master-agent/references/protocols`
on Codex, `~/.claude/skills/master-agent/references/protocols` on Claude.
Read `00-contract.md` and `debug.md`, then perform the diagnosis.
If a dependency is unavailable, report its exact path before a bounded fallback.
Do not claim the v2 role ran when it did not load.

Reuse any existing DEBUG or INVESTIGATE evidence and loop. Preserve the fast
reproducer, targeted instrumentation and regression proof from this skill's
earlier workflow. There is no required number of hypotheses: add a hypothesis
only when evidence and a probe can distinguish it from the others.
Finish with `>> DEBUG COMPLETE` when the diagnosis is complete; report an
unfinished fix separately. Follow the user's existing fix authorization.
