# ADR-001: File-based persistence (no database dependency)

## Status: Accepted

## Context

Hive is designed to be self-hostable, easy to run locally, and adaptable across
environments. The core framework already records runs, decisions, and logs on disk.
Requiring a database would raise the barrier to entry and complicate development
and deployment.

## Decision

Use file-based persistence as the default storage mechanism for core runtime data
(runs, decisions, logs, and sessions). Database-backed storage is intentionally
not a requirement for running the framework.

## Consequences

- Keeps the framework lightweight and easy to run in local or self-hosted setups.
- Supports portability of agent runs and artifacts without external dependencies.
- Limits concurrency and cross-process coordination at scale; future storage
  migrations may introduce optional database adapters.

