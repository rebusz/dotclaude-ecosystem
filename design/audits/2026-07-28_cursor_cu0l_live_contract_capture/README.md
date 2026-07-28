# Cursor CU0-L live contract capture

Date: 2026-07-28
Risk: R1
Authorization: `GO CURSOR CU0-L LIVE CONTRACT CAPTURE`

## Outcome

- Cursor Agent CLI is eligible for CU1. Two independent new chats produced
  matching `sessionStart`/`sessionEnd` pairs, exact Temp-only context nonce
  responses, and absolute existing `.jsonl` transcript paths at end.
- Resume retained the same identity and emitted `sessionEnd` without a second
  `sessionStart`. A new chat produced a distinct identity.
- Abrupt termination produced `sessionStart` only; the probe did not synthesize
  `sessionEnd`.
- Cursor IDE delivered the exact context nonce and emitted distinct
  `sessionStart` events, but neither New Agent nor application close emitted a
  matching `sessionEnd`. IDE therefore remains degraded and is excluded from
  CU1.
- `preCompact` remains unproven on both surfaces because this capture had no
  deterministic bounded trigger.

## Containment and restoration

- The initial run was invalidated when unrelated Cursor Agent tasks appeared
  after preflight. Its two invalid-JSON invocations are non-promotable.
- The user-level hook target was absent before capture and is absent after
  capture.
- Parent ACL matched the captured pre-state after restoration.
- Final readback found zero Cursor processes and zero probe processes.
- No lifecycle state, production adapter, persistent hook activation,
  Antigravity, or Kimi action occurred.

The aggregate, sanitized result is in `evidence.json`. Raw Temp manifests and
logs remain outside the repository because they contain probe nonces and
unredacted experiment output.

## Next authorization boundary

The smallest eligible implementation slice is CLI-only and requires:

`GO CURSOR CU1 CLI ADAPTER IMPLEMENTATION`
