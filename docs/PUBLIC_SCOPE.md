# Public export scope

## Included

- Frozen-M5 continuity contracts and deterministic local implementations.
- Local SQLite/event/outbox/receipt mechanics.
- Provider-neutral request, response, observability, and redaction boundaries.
- Prompt-cache identity and retention policy code.
- Selected synthetic tests covering the exported contracts.
- New portfolio documentation describing the architecture, frozen boundary, safe setup, and limitations.

## Omitted by design

- The private Git history and all branches/tags.
- The HTTP gateway spine and private UI payloads.
- The Android relay, APK/build artifacts, screenshots, and branding assets.
- The live MCP server, Codex hand/tool bridge, deployment scripts, VPS/runbook material, and live configuration.
- Chat-history imports, Memory Vault exports, source attachments, transcripts, raw provider requests/responses, trace captures, databases, logs, and private fixtures.
- M5 live harnesses, canary/diagnostic scripts, and operational status-lock reports.
- The copied third-party Drivesoid source tree and its upstream provenance material.
- Bytecode, generated payloads, caches, and other non-source artifacts.

The omissions preserve the meaning of the included core without exposing private data or environment topology. They do not imply that the omitted private surfaces were absent from the frozen M5 system.

## Export-only adjustment

Two export-only sanitizations were applied: one historical attestation string that pointed to a private absolute path was replaced with an explicit `examples/private-root-not-included/...` marker, and test-only credential-shaped labels were renamed to `TEST_ONLY_...` with one synthetic title made explicitly restricted. No runtime provider, persistence, or semantic behavior was intentionally changed for this export.
