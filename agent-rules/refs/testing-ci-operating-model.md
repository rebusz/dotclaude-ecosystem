# Shared Testing and CI Operating Model

## Status and boundary

This is a versioned, opt-in contract. Publishing the library does not activate
selected CI in any repository. A repository remains on its current workflow
until its own reviewed adapter and evidence gate explicitly authorize a change.

The shared tool never scans `D:/APPS`, edits branch protection, changes a
workflow, marks a PR ready, starts tests, or calls a broker/runtime. It accepts
one explicit Git worktree and refuses missing, invalid, unsupported-major, or
remote-mismatched adapters before writing files.

## Cost discipline

- Develop implementation PRs as drafts so draft-skipped CI does not spend paid
  minutes.
- Validate locally and batch changes before the one ready transition.
- One ready head gets one required run. A red result is classified from exact
  artifacts before a bounded probe; it is never blindly rerun.
- Scheduled full-health evidence and actual candidate evidence are separate.
  Cache hits and old green runs are not proof for a new base/head identity.
- Cost estimates are planning data. They are not invoice truth and never weaken
  a safety or required-check gate.

## Adapter contract

An opted-in repository owns `.ci/ci-model.json` with schema
`ci_model_adapter_v1`. It declares:

- repository identity and owners;
- T0, local-focused, full-CI, and collection commands;
- repository-local diagnostic artifact root;
- supported OS/Python/Node/runtime identities;
- critical path rules and mandatory risk bundles;
- risk-to-tier policy and candidate mode;
- exact-base TTL and scheduled full-health command;
- dependency pins and required-check identity;
- cost rate/source/effective date;
- rollback-to-full command;
- supported shared contract `MAJOR.MINOR` range.
- activation verdict, evidence SHA-256, and reviewed evidence-head SHA.

Invalid or absent adapters mean STOP and no writes. Unsupported majors are
refused before diff generation. Repository-specific commands stay in adapters,
not in the shared source.

## Selection law

1. Normalize repository-relative paths and reject traversal/drive paths.
2. Apply critical rules before optional graph information.
3. Add mandatory bundles for the declared risk class.
4. Deletion/rename escalates to full.
5. Missing/stale/corrupt graph widens; it never removes rule-selected tests.
6. Unknown production surfaces escalate to full.
7. A non-empty diff selecting no tests is invalid.
8. `candidate_mode: full` always emits the full CI command.
9. Output is canonical-JSON hash bound to adapter, base, head, risk, paths,
   graph state, tests, reasons, and escalation.

## Evidence and activation

Selected candidate mode requires repository-owned historical replay evidence:
zero known-regression and critical-category misses, complete production-path
classification, deterministic platform parity, provenance-fault injection, and
manual no-future-label-leak review. Any miss means HOLD and full candidate mode.

Activation is a repository-local evidence-bound operation. A global library
merge, adapter sync, plan GO, or shared-tool PASS is never an activation token.
An adapter requesting `candidate_mode: selected` is invalid unless its activation
record is `PASS` and includes syntactically valid evidence and reviewed-head
hashes; repository review must still verify that those identities are current.

## Sync and rollback

`scripts/sync_ci_policy.py --repo <exact-worktree> --adapter <path> --check`
shows drift for one target. `--write` atomically copies the shared package and a
hash manifest under `.ci/_shared/`; it does not edit workflows. Repositories
review those generated files in their own adapter PR.

Rollback is repository-owned: set candidate mode to full and execute the
declared `rollback_to_full` command. Shared evidence is retained for diagnosis.
If the shared orchestrator fails, the repository fallback is a direct full
suite, never success or skip.
