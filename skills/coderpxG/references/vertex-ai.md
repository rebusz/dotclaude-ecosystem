# GCP Vertex AI authoring route

This integration is prepared for response-only authoring on GCP Vertex AI.
The cloud author has no local file, shell or test access. A qualified local
integrator is responsible for applying returned changes and running the real
local checks.

## Secret scanning and context boundaries

Before any outbound submission, scan the complete rendered packet including
attachments for secrets and reject any unsafe packet. Limit it to authorized,
necessary context. Keep handoffs, credentials and `.env` contents local.

## Routing and readiness

Use the installed CoderPX dispatcher and its registered Vertex selector for the
task. For supervised assignments, enter through `dispatch.py lane` with the
supported role. Mark Vertex active only after an ordinary entry-point receipt
identifies Vertex as the provider that actually served the assignment. Local
fixtures, a catalog entry and a direct adapter smoke do not qualify the route.
Keep Google AI Studio outside the Vertex fallback chain.

## Model identity and telemetry

Distinguish requested model from the returned `modelVersion` and requested effort
from a provider-returned actual effort (unverified when absent).
`usageMetadata`/reported tokens support usage, and actual cost stays UNKNOWN
without billing readback.

## Interrupted streams and submit state

After possible submit, interrupted SSE without confirmed terminal completion
holds the original assignment as `SUBMIT_UNCONFIRMED`, preserving job ID,
reservation, response evidence, no retry, replacement or fallback.

## Review gate and policy boundaries

Require independent different-family review of exact locally applied head via
`dispatch.py lane review` before landing.
