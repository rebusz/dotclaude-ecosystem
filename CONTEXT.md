# Ecosystem Automation Domain Language

## TruthDeck

A read-only evidence compiler. It observes external sources, produces immutable
snapshots, evaluates evidence gates, and recommends one permitted next action. It
does not own work, execute workflows, or mutate application repositories.

## Conductor

The local cross-repository work coordinator. It admits work into a durable queue,
orders eligible work, assigns it to compatible agent hosts, tracks ownership, and
requires evidence before state transitions. It does not decide technical truth or
replace the workflow that owns a task.

## Work Item

A bounded unit of intended work with a repository scope, desired terminal stage,
risk class, dependencies, and explicit authority requirements.

## Attempt

One execution of a Work Item by one Agent Instance. A retry creates a new Attempt
and never rewrites the history of an earlier Attempt.

## Claim

The durable record that an Agent Instance has accepted an Attempt.

## Lease

The time-bounded right of an Agent Instance to continue an Attempt. Lease expiry
removes exclusive ownership but does not prove that repeating side effects is safe.

## Evidence Checkpoint

A reference to an immutable TruthDeck snapshot and required workflow artifacts used
to decide whether a Work Item may cross a lifecycle boundary.

## Agent Host

A product or runtime capable of participating in the queue, such as Claude, Codex,
Cursor, Gemini, Kimi, or Antigravity.

## Agent Instance

One concrete session, task, or process running on an Agent Host.

## Host Adapter

A bounded integration that lets one Agent Host discover, claim, execute, report, or
resume Work Items. Capability is proven per operation; support is never inferred
from a vendor name.

## Executor

An Agent Instance that performs a Work Item inside the authority and filesystem
boundaries attached to that item.

## Provider

An external model, browser lane, or service used by an Executor. A Provider is not
an Agent Host unless it independently implements the client contract.

## CDP Fleet Manager

The separate owner of browser-lane scheduling, health, identity, and lifecycle. The
Conductor may submit a bounded provider job through its published adapter, but never
owns Chrome processes or CDP leases.
