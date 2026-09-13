# House of Us — frozen M5 portfolio snapshot

House of Us is a private, local-first continuity system for an AI companion runtime. It treats continuity as an engineered system boundary: provider output is a candidate, runtime policy evaluates it, and durable state changes pass through explicit contracts, identity checks, and append-only receipts.

This repository is a public portfolio snapshot of the frozen M5 state. It contains the sanitized M5 continuity core and selected deterministic local tests. It is designed for technical review and local inspection; it is not the private House deployment and it does not contain production data, credentials, provider traces, the Android app, or the canonical repository history.

## What M5 demonstrates

- A provider-neutral request/response boundary that keeps provider transport separate from House semantics.
- Candidate, evaluation, and durable-write stages with explicit authority boundaries.
- Immutable operation identities, idempotency, predecessor binding, and fail-closed recovery paths.
- SQLite-backed local continuity state with event, Working-Set, context, and outbox structures.
- Deterministic context shaping and compact provider-visible projections.
- Prompt-cache identity based on the final provider-facing material rather than an informal semantic label.
- Local observability and redaction contracts that prevent credentials and raw private bodies from entering ordinary diagnostics.
- Synthetic, no-provider tests for contract validation, replay resistance, scope handling, cache identity, and trace safety.

The private M5 freeze record reports the complete system as **M5 activated and verified**. This export intentionally exposes only the portion that can be safely reviewed outside House.

## Architecture

```text
provider candidate
        |
        v
neutral request + runtime evaluation
        |
        v
identity / predecessor / scope / idempotency gates
        |
        v
local event store + Working Set + context projection
        |
        v
durable preparation outbox + receipts
        |
        v
provider-visible projection and diagnostics
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the ownership boundaries and [docs/M5_OVERVIEW.md](docs/M5_OVERVIEW.md) for the frozen-snapshot interpretation.

## How it was built

Astel owns the product direction and acceptance bar: requirements, architecture, privacy boundaries, prioritization, test strategy, failure analysis, and final validation. Codex and other AI coding agents implemented bounded modules, tests, documentation, and mechanical refactors under that direction. This is product and systems ownership, not a claim that Astel manually authored code she did not write.

## Local inspection

Prerequisite: Python 3.10 or newer. The public test slice uses only the Python standard library.

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src;tests"
py -3.14 -m unittest discover -s tests -p "test_*.py"
```

macOS/Linux:

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_*.py'
```

The tests are synthetic/local and are expected to make zero provider, network, deployment, or canonical-data calls. They exercise the exported core only; a passing run is not proof of the private service, Android APK, subscription route, or live provider configuration.

## Scope and limitations

The snapshot boundary is the frozen M5 commit recorded in the private repository. POST-M5 and W1 development is not included. The private gateway/UI, Android relay, live MCP/deployment bridge, operational runbooks, chat-history and Memory exports, live traces, screenshots, generated artifacts, and third-party source checkout were omitted because they are private, environment-specific, data-bearing, or unnecessary for portfolio review. The omissions are listed in [docs/PUBLIC_SCOPE.md](docs/PUBLIC_SCOPE.md).

This repository is not a turnkey deployment. It does not include a provider key, production endpoint, private configuration, database, or real conversation data. The code is published for portfolio inspection only.

## License status

No open-source license is granted for this portfolio snapshot. All rights are reserved. Dependencies named by the private repository are not redistributed here, and the copied third-party Drivesoid checkout was excluded. One House module contains an adapted MIT-licensed MCP-client component; its attribution and notice are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
