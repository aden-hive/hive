# ADR-004: Coding agent as the primary builder interface

## Status: Accepted

## Context

Hive is goal-driven: users describe desired outcomes, and the framework generates
graphs, nodes, and connection logic. Coding agents (Claude Code, Codex CLI, Cursor,
Opencode) already provide the best interactive experience for this workflow.

## Decision

Treat the coding agent workflow as the primary interface for building agents.
CLI and manual definitions remain supported, but the default path is to build
through the agent builder skills and MCP tools.

## Consequences

- Maximizes developer velocity and aligns with goal-driven design.
- Encourages structured goals, success criteria, and constraints by default.
- Requires contributors to set up coding agent tooling to get the best experience.

