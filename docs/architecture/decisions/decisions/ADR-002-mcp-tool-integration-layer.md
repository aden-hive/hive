# ADR-002: MCP as the tool integration layer

## Status: Accepted

## Context

Hive agents need access to external systems (files, web, APIs, internal services).
The framework also needs to support both local development and production
deployments with consistent tool discovery and usage.

## Decision

Adopt Model Context Protocol (MCP) as the standard integration layer for tools.
Tools are exposed via MCP servers over STDIO or HTTP, and agents discover and use
them through the framework's MCP registry.

## Consequences

- Standardized tool contracts enable consistent integration across environments.
- Tools remain decoupled from the core runtime and can evolve independently.
- Reliability depends on MCP server availability and compatibility.

