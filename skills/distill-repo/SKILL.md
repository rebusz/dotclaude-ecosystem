---
name: distill-repo
description: Distill a repository into lazy-loadable repo skills and bounded PACKET digests from verified code, tests, CI, design docs, handoffs, readbacks, memory pointers, and git history. Use when the operator asks to build or refresh a per-repo skill library, generate repo-scoped .claude/skills, create managed AGENTS.md skill pointers, or prepare skill PACKET context for external audit/fusion models.
---

# Distill Repo

Create a verified skill library for one target repo. This `distill-repo`
builder skill lives globally in `dotclaude-ecosystem`; the generated repo
library it produces lives in the target repo. Treat the output as derived
operational knowledge, not a new authority layer.

## Hard Boundaries

- Write only to `<target-repo>/.claude/skills/**` and the managed block in
  `<target-repo>/AGENTS.md`.
- Replace only text between these exact markers:
  `<!-- BEGIN distill-repo skills -->` and
  `<!-- END distill-repo skills -->`.
- Never write product code, runtime config, broker API code, order path code,
  credentials, local env files, generated logs, or unrelated docs. This is a
  scope limit on THIS skill (it authors skills, not product code) — not a claim
  that agents may never edit execution code; see
  `agent-rules/refs/paper-live-parity.md`.
- Distilled skills must describe the real-money/Combine TRIGGER gate and
  paper/live parity accurately, and must not reintroduce a blanket
  "agents never touch the order path" prohibition.
- Memory and claude-mem are pointers, not truth. Verify memory-sourced claims
  against code, tests, CI, design docs, readbacks, or git before treating them
  as facts.
- If no explicit per-run workflow budget is provided, stop before multi-agent
  authoring and ask for a budget.

## Source Order

Use stronger evidence before weaker evidence:

1. Code and in-repo schemas.
2. Tests, fixtures, and validation scripts.
3. CI workflows and build/lint commands.
4. Design plans, handoffs, audits, readbacks, and release notes.
5. MEMORY.md and claude-mem pointers, only after repo verification.
6. Git log and PR history.
7. Labelled inference.

Label unverifiable memory-sourced claims as `[MEMORY-unverified]`. Label
inferred claims as `[INFERRED - verify]`. Do not put unverified or inferred
claims in a PACKET as verified project facts.

## Workflow

### 1. Budget and Freeze

Record:

- target repo absolute path;
- output scope;
- max elapsed time;
- max agents by class;
- max paid/frontier lanes;
- no-go paths;
- current dirty-tree boundaries.

Stop if the budget or no-go paths are missing.

### 2. Discovery Census

Use the assigned workflow model for mechanical discovery; bound the reads, not
the model capability:

- repo root instructions: `AGENTS.md`, `CLAUDE.md`, nested agent files;
- entry points and public commands;
- tests and CI workflows;
- design/plans, design/audits, design/visions, handoffs, readbacks;
- tools/scripts that operators already use;
- git history for shipped incidents or repeated fixes;
- memory pointers that mention the target repo.

Discovery is read-only. Do not run mutating commands. Produce at least eight
candidate skills with one-line rationale each, or explicitly list taxonomy gaps
that explain why fewer candidates are correct.

### 3. Taxonomy Menu

Prefer repo-specific, trigger-rich skills over generic README-shaped skills.
Common categories:

- architecture contract;
- change control and risk classes;
- run and operate;
- build and environment;
- validation and QA;
- debugging playbook;
- feature or campaign runbook;
- input/data/domain reference;
- failure archaeology;
- docs and writing canon;
- research or replay methodology;
- external integration boundaries.

Merge candidates when their triggers overlap. Split candidates when one skill
would contain two distinct "when not to use" boundaries.

### 4. Model Routing

Spend model quality where judgment matters:

| Work | Model tier |
|---|---|
| Census, grep, file lists, git-log summaries | inherited workflow model |
| Procedural runbooks and FACTUAL review | inherited workflow model |
| Architecture, failure archaeology, change control, doctrine, usability, fixer | inherited workflow model or explicitly selected frontier |

Use parallel agents only for disjoint questions or disjoint write scopes. Do
not ask two agents to author the same skill independently unless this is an
explicit review/evaluation pass.

### 5. Author Skills

Each generated `SKILL.md` must contain:

- YAML frontmatter with only `name` and `description`;
- `trigger-phrases` as an ASCII list in the body;
- a concrete runbook grounded in repo evidence;
- `PACKET` digest of 500 tokens or fewer;
- provenance with source paths and verification commands;
- re-verification commands;
- sibling boundary: `owns X / defers to <skill> for Y`;
- "When not to use" section;
- risk-class and live-boundary reminders when relevant.

Descriptions are trigger surfaces. Include when to use the skill in the
frontmatter description, not only in the body.

### 6. PACKET Contract

Write PACKET for external models that cannot inspect the repo. Keep it compact,
specific, and audit-safe:

```text
PACKET:
  id: <repo-skill-slug>
  source_skill: <relative path>
  verified_facts:
    - <fact with source path or command>
  red_lines:
    - <boundary>
  commands:
    - <read-only verification command>
  when_to_use:
    - <trigger phrase>
  when_not_to_use:
    - <sibling or boundary>
```

Do not include secrets, account IDs, tokens, env values, or local credentials.
Flag names are acceptable; values are not.

### 7. Managed AGENTS Block

Add or replace only the distill-repo block:

```markdown
<!-- BEGIN distill-repo skills -->
- `<skill-name>`: <one-line trigger and pointer to .claude/skills/.../SKILL.md>
<!-- END distill-repo skills -->
```

If `AGENTS.md` is missing, create it only when the operator explicitly allowed
AGENTS pointer generation for the target repo.

### 8. Reviews

Run three review passes before reporting done:

- FACTUAL: every command/path/source exists or is clearly labelled. Read-only
  commands are executed verbatim when practical.
- DOCTRINE: generated skills do not contradict `AGENTS.md`, `CLAUDE.md`,
  agent-rules refs, risk classes, or live-money boundaries.
- USABILITY: a cold agent can pick the right skill from descriptions and can
  answer the intended operator prompt without memory.

Fix P1/P2 findings. Note lower-severity follow-ups only after the library is
usable.

## Minimal Dry-Run Harness

Before creating a PR, validate a representative fixture output:

1. Parse every generated skill frontmatter.
2. Check required fields: `description`, `trigger-phrases`, `PACKET`,
   provenance, re-verification commands, sibling boundary, and when-not-to-use.
3. Confirm discovery emitted at least eight candidates or explicit taxonomy
   gaps.
4. Grep generated outputs for secret/account-like values.
5. Verify FACTUAL, DOCTRINE, and USABILITY review notes are represented.
6. Run the bundled validator against the target repo:

   ```bash
   python <this-skill>/scripts/validate_distilled_library.py <target-repo> --discovery <candidate-report>
   ```

7. Run `git diff --check`.

Example secret/account grep targets:

```bash
rg -n "token|secret|password|api[_-]?key|account[_-]?(id|number)|PROJECTX_.*=|IBKR_.*=" <target-repo>/.claude/skills <target-repo>/AGENTS.md
```

Treat matches as findings to inspect, not automatic failure; flag names may be
legitimate while values are not.

Use `scripts/validate_distilled_library.py` for the mechanical gate. It checks
frontmatter, required sections, PACKET presence, provenance/re-verification
terms, sibling boundaries, managed block markers, optional discovery candidate
count, and secret/account-like values.

## Reporting

Report:

- repo, branch, and PR URL if opened;
- changed files only;
- dirty boundaries preserved;
- exact validation commands and exit codes;
- accepted taxonomy or taxonomy gaps;
- review pass results;
- next required GO token.
