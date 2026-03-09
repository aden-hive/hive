# MCP Client Architecture (Scope A)

This package contains Hive's modular MCP client implementation.

## Scope boundary

Implemented in Scope A:
- transport/session/auth modularization
- HTTP `401` handling
- direct `auth_url` surfacing (`auth_required`)
- token lookup/reuse from credential store
- retry with bearer token
- deterministic external auth-required response (`auth_required_external`)

Deferred to Scope B:
- OAuth metadata discovery execution
- PKCE flow execution
- authorization code exchange/token minting
- brokered OAuth start/complete orchestration with Aden

## Package structure

- `models.py` and `errors.py`
: shared data contracts and typed exceptions.
- `config/`
: MCP config loading + stdio path resolution.
- `transport/`
: transport-only logic (`stdio`, `http`), no credential persistence logic.
- `auth/`
: challenge parsing, payload construction, token lookup strategy, auth orchestration.
- `integrations/`
: adapter boundary for provider-specific behavior; generic adapter in Scope A.
- `session/`
: orchestration of transport + auth flow + retry behavior.
- `client/`
: stable facade used by runner/tool registry.

## Runtime behavior (HTTP, Scope A)

1. Call MCP endpoint.
2. If successful, continue.
3. On `401`:
   - parse challenge (`WWW-Authenticate` + response hints),
   - if `auth_url` exists => return `auth_required`,
   - otherwise attempt token reuse from credential store,
   - retry once with bearer token if found,
   - if still unauthorized (or no token) => return `auth_required_external`.

## Compatibility

`core/framework/runner/mcp_client.py` remains a compatibility shim and forwards to this package.

## Testing guidance

Tests live in `core/framework/mcp/tests/` and should focus on:
- parser/payload/strategy unit behavior
- manager orchestration decisions
- session runtime retry/auth-required branches
- config resolver path handling

