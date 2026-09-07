---
name: investigate
description: Diagnose a concrete bug or regression through a reproducer and discriminating probes. Shares the DEBUG protocol; fixes follow the existing task authorization.
---

# Investigate

Resolve the installed protocol library: `~/.codex/skills/master-agent/references/protocols`
on Codex, `~/.claude/skills/master-agent/references/protocols` on Claude.
Read `00-contract.md` and `debug.md`, then run one diagnosis loop.
Report an exact missing dependency instead of claiming the protocol was loaded.

Retain the incident's existing evidence, runtime identity, hypotheses and
authorization. Do not restart the investigation when handed off from DEBUG,
`/diagnoze` or `/diagnose`. Use the requested mode's closing tag; for this
entry use `>> INVESTIGATION COMPLETE` after diagnosis is complete.

A request for diagnosis alone does not imply live restart or deployment.
A request to fix the issue carries ordinary in-scope local work forward
under existing risk and trigger rules. Re-run a wider suite only when changed
behavior or an unresolved failure justifies it.
