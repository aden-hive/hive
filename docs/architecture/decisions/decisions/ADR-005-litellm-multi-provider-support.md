# ADR-005: LiteLLM for multi-provider LLM support

## Status: Accepted

## Context

Hive needs to support multiple LLM providers (hosted and local) while keeping the
core runtime provider-agnostic. A single abstraction reduces integration cost and
keeps agent configuration consistent.

## Decision

Use LiteLLM as the primary LLM integration layer in the framework to support
multiple providers behind a common interface.

## Consequences

- Provides broad provider coverage with minimal code changes.
- Simplifies configuration across OpenAI, Anthropic, Gemini, and local models.
- Introduces dependency on LiteLLM compatibility and release cadence.

