# M5 architecture

## Ownership flow

1. A provider adapter produces a neutral candidate. Transport details stay at the adapter boundary.
2. Runtime evaluation separates provider intent from House-owned semantic and durable-write decisions.
3. Gate contracts validate exact schemas, participant authorship, scope, predecessor identity, and idempotency.
4. Local stores append events and receipts. Reopening a root or replaying an identity cannot silently create a second durable effect.
5. Context projection selects bounded, eligible material for the next provider-facing request. Private source bodies are not part of ordinary diagnostics.
6. Prompt-cache identity is derived from the final material sent to the provider, preserving exact request identity across provider-facing construction.

## Why the separation matters

The system distinguishes semantic meaning from integrity mechanics. A provider can propose; House evaluates. A durable write can be accepted only after the exact operation, predecessor, scope, and receipt contracts pass. Failed formal identities remain historical evidence and are not retried, relabeled, or reused.

The public tree includes the core contracts, local stores, continuity gates, neutral provider boundary, prompt-cache policy, and selected tests. The private HTTP gateway, phone surface, service configuration, live provider route, and data vault remain outside this repository.

## Runtime posture

The exported tests are local and synthetic. No API key is needed, no provider call is expected, and all temporary SQLite state is created under test-managed temporary directories. Any real deployment or live transport requires separate private configuration and authorization that is intentionally absent here.
