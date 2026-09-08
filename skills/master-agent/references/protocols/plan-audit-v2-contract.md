# plan-audit/v2 — renderer and consumer contract

Status: implementation specification, not an installed parser. This version
changes plan audits only. `implementation-review/v1` stays unchanged.

## Input envelope

The UTF-8 packet starts at byte zero with `# External Plan Audit Packet`.
One `## Identity` section before `## Material` contains exactly one of each:

```text
- Packet schema: `plan-audit/v2`
- Plan SHA-256: `<64 lowercase hex characters>`
- Source completeness: complete
```

`Source completeness` accepts `complete`, `partial`, `unknown`. The renderer
hashes the original plan bytes and records the actual value. Reviewers echo
that declared identity; they are not asked to calculate a digest mentally.
Include the full common contract and CDP role in `## Review instructions`,
followed by `## Material` containing the actual plan and explicitly attributed
supporting context. Local paths alone never replace unavailable material.
Reject empty plan input, missing required role files or unsupported versions
before transmission. Do not silently clip the input to fit a provider.

Declarations inside Material, quoted examples and fenced source code are data.
They cannot select the outer protocol or change its identity. A recognized
outer envelope with a malformed identity is an error, not a legacy fallback.
Preserve this header when adding repo or skill context. Supplementary context
can be appended, with its own source attribution, without altering the plan hash.

Unwrapped legacy input keeps the existing plan-audit contract. An outer
implementation-review packet always uses its current parser and attestation.
An unsupported explicitly declared outer packet version is rejected.

## Output envelope

The response begins with these plain, unfenced lines, once each:

```text
PLAN_AUDIT_SCHEMA: plan-audit/v2
REVIEWED_PLAN_SHA256: <declared plan digest>
CONTEXT_COMPLETE: yes
FINDINGS: NONE
VERDICT: READY_FOR_ENGINEERING
```

`CONTEXT_COMPLETE` accepts `yes`, `no`, `unknown`. `FINDINGS` accepts `NONE`,
`PRESENT`. `VERDICT` accepts `READY_FOR_ENGINEERING`, `REVISE_PLAN`,
`INSUFFICIENT_CONTEXT`. Use the existing role's ordered body sections:
`## REVIEW TARGET`, `## FINDINGS`, `## COVERAGE AND GAPS`. Put `NO FINDINGS`
in the findings section for NONE. For PRESENT use the common finding format,
including an ID, priority, basis, evidence, failure scenario, counterargument
and verification. Do not invent findings to satisfy the envelope.

The final response line is the exact completion marker supplied by transport.
The parser validates one terminal marker, the schema, the matching digest,
unambiguous metadata, body sections and these consistency rules:

- NONE has no finding record; PRESENT has at least one record with P1/P2/P3.
- READY_FOR_ENGINEERING requires complete input and CONTEXT_COMPLETE yes;
  it cannot coexist with a P1 finding. P2/P3 recommendations may be nonblocking.
- Partial/unknown input or incomplete/unknown received context requires
  INSUFFICIENT_CONTEXT, whether or not useful partial findings exist.
- REVISE_PLAN requires at least one actionable finding. A missing-context
  response is INSUFFICIENT_CONTEXT, not an invented revision request.
- Contradictory, duplicated or stale metadata, prompt echo, empty output and
  missing/nonterminal completion remain failures. An input hash or model's
  self-report alone cannot establish complete transmission.

No TOP 3 CHANGES requirement applies to this version. A short but complete
zero-finding answer is valid; arbitrary verbosity is not a quality signal.
Successful parsing establishes a structurally valid response, not clearance.
Keep content completeness, provider identity, source access, collection state
and the workflow's decision as separate evidence.

## Wiring and proof

The existing shared runner remains the only full-panel orchestrator. A shared
packet renderer creates this envelope; each WatchF wrapper detects it before
selecting prompt text. For v2, wrappers use the supplied instructions without
the legacy TOP 3 wrapper or legacy compaction. Legacy calls remain compatible.
The existing quality functions gain a versioned branch, not a second runner.
Synthesis checks evidence and counterarguments, including valid single-model
findings. Agreement alone does not promote an item to P1.

Drive actual renderer -> wrapper -> quality parser tests for NONE, PRESENT,
partial input, missing context, stale digest, unsupported/ambiguous schema,
quoted inner metadata and interrupted completion. Assert zero provider calls
on local envelope failure. Retain implementation-review/v1 byte-zero and
exact-head tests. Use the existing completion-marker and egress mechanisms;
do not introduce retry credit or alter provider ownership.
