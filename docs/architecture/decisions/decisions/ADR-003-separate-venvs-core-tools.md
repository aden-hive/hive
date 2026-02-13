# ADR-003: Separate virtual environments for core and tools

## Status: Accepted

## Context

The framework (`core/`) and tools package (`tools/`) are separate Python packages
with different dependency sets. Tools often require additional libraries and
credentials that should not be forced onto the core runtime.

## Decision

Maintain separate virtual environments for the core framework and the tools
package. The quickstart/setup flow installs each package independently.

## Consequences

- Reduces dependency conflicts and keeps the core runtime lightweight.
- Allows tools to evolve rapidly without destabilizing the core package.
- Adds setup complexity for contributors and requires clear documentation.

