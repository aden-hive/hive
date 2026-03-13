# MCP Server Registry — Product & Business Requirements Document

**Status**: Draft v2
**Last updated**: 2026-03-13
**Authors**: Timothy
**Reviewers**: Platform, Product, OSS/Community, Security

---

## 1. Executive Summary

This document proposes an **MCP Server Registry** system that enables open-source contributors and Hive users to discover, publish, install, and manage MCP (Model Context Protocol) servers for use with Hive agents.

Today, MCP server configuration is static, duplicated across agents, and limited to servers that Hive spawns as subprocesses. This makes it impractical for users who run their own MCP servers on the same host, and impossible for the community to contribute standalone MCP integrations without modifying Hive internals.

The registry consists of three components:
1. **A public GitHub repository** (`hive-mcp-registry`) — a curated index where contributors submit MCP server entries via pull request
2. **Local registry tooling** — CLI commands and a `~/.hive/mcp_registry/` directory for installing, managing, and connecting to MCP servers
3. **Framework integration** — changes to Hive's `ToolRegistry`, `MCPClient`, and agent runner so agents can flexibly select which registry servers they need

---

## 2. Problem Statement

### 2.1 Current State

- Each Hive agent has a static `mcp_servers.json` file that hardcodes MCP server connection details.
- All 150+ tools live in a single monolithic `mcp_server.py` — contributors add tools to this one server.
- There is no mechanism for standalone MCP servers (e.g., a Jira MCP, a Notion MCP, or a custom database MCP) to be discovered or used by Hive agents.
- Each agent spawns its own MCP subprocess — no connection sharing across agents.
- Only `stdio` and basic `http` transports are supported. No unix sockets, no SSE, no reconnection.
- External MCP servers already running on the host cannot be easily registered.

### 2.2 Who Is Affected

| Persona | Pain Point |
|---|---|
| **OSS contributor** | Wants to publish a standalone MCP server for the Hive ecosystem but has no pathway to do so without modifying Hive core |
| **Self-hosted user** | Runs multiple MCP servers on the same host (Slack, GitHub, database tools) and wants Hive agents to discover them |
| **Agent builder** | Copies the same `mcp_servers.json` boilerplate across every agent; no way to say "use whatever the user has installed" |
| **Platform team** | Cannot manage MCP servers centrally; each agent manages its own connections independently |

### 2.3 Impact of Not Solving

- The Hive MCP ecosystem remains closed — growth depends entirely on tools being added to the monolithic server.
- Users with existing MCP infrastructure (from Claude Desktop, Cursor, or other MCP-compatible tools) cannot leverage it with Hive.
- Resource waste from duplicate subprocess spawning across agents.
- No path to community-contributed integrations beyond the core tool set.

---

## 3. Goals & Success Criteria

### 3.1 Primary Goals

| # | Goal | Metric |
|---|---|---|
| G1 | A contributor can register a new MCP server in under 5 minutes | Time from fork to PR submission |
| G2 | A user can install and use a registry MCP server in under 2 minutes | Time from `hive mcp install X` to first tool call |
| G3 | Agents can dynamically select MCP servers by name or tag without hardcoding configs | Agents use `mcp_registry.json` selectors instead of full server configs |
| G4 | Multiple agents share MCP connections instead of duplicating them | One subprocess/connection per unique server, not per agent |
| G5 | External MCP servers already running on the host can be registered with a single command | `hive mcp add --name X --url http://...` works end-to-end |
| G6 | Zero breaking changes to existing agent configurations | All current `mcp_servers.json` files continue to work unchanged |

### 3.2 Developer Success Goals

| # | Goal | Metric |
|---|---|---|
| G7 | First-install success rate exceeds 90% | Successful `hive mcp install` / total attempts (tracked via CLI telemetry opt-in) |
| G8 | First-tool-call success rate exceeds 85% after install | Successful tool invocation within 5 minutes of install |
| G9 | Users can self-diagnose and resolve config/auth issues without filing support tickets | Median time from error to resolution <5 minutes; support ticket volume per server <1/month |
| G10 | Registry entries remain healthy over time | % of entries passing automated health validation at 30/60/90 days |
| G11 | Server upgrades do not silently break agents | Zero undetected tool-signature changes on upgrade |

### 3.3 Non-Goals (Explicit Exclusions)

- **Billing or monetization** — the registry is free and open-source.
- **Hosting MCP servers** — the registry only stores metadata; actual servers are installed/run by users.
- **Replacing `mcp_servers.json`** — the static config remains for backward compatibility and offline use.
- **Runtime agent-to-agent MCP sharing** — this is about discovery and connection, not inter-agent protocol.
- **Decomposing the monolithic `mcp_server.py`** — this is a future phase, not part of the initial build.

---

## 4. User Stories

### 4.1 Contributor: Publishing an MCP Server

> As an OSS contributor who has built a Jira MCP server, I want to register it in a public registry so that any Hive user can install and use it without modifying Hive code.

**Acceptance criteria:**
- `hive mcp init` scaffolds a manifest with my server's details pre-filled from introspection.
- `hive mcp validate ./manifest.json` passes locally before I open a PR.
- `hive mcp test ./manifest.json` starts my server, lists tools, calls a health check, and reports pass/fail.
- CI validates my manifest automatically (schema, naming, required fields, package existence).
- After merge, the server appears in `hive mcp search` for all users.

### 4.2 User: Installing an MCP Server from the Registry

> As a Hive user, I want to install a community MCP server and have my agents use it immediately.

**Acceptance criteria:**
- `hive mcp install jira` fetches the manifest and configures the server locally.
- If credentials are required, the CLI prompts me: "Jira requires JIRA_API_TOKEN (get one at https://...). Enter value:"
- `hive mcp health jira` confirms the server is reachable and tools are discoverable.
- My queen agent (with `auto_discover: true`) automatically picks up the new server's tools.
- `hive mcp info jira` shows trust tier, last health check, installed version, and loaded tools.

### 4.3 User: Registering a Local/Running MCP Server

> As a user running a custom database MCP server on `localhost:9090`, I want Hive agents to use it without publishing it to any public registry.

**Acceptance criteria:**
- `hive mcp add --name my-db --transport http --url http://localhost:9090` registers it.
- The server appears in `hive mcp list` and is available to agents that include it.
- If the server goes down, Hive logs a warning with actionable next steps and retries on next tool call.

### 4.4 Agent Builder: Selecting MCP Servers for a Worker

> As an agent builder, I want my worker agent to use specific MCP servers (e.g., Slack + Jira) without hardcoding connection details.

**Acceptance criteria:**
- I create `mcp_registry.json` in my agent directory with `{"include": ["slack", "jira"]}`.
- At runtime, the agent automatically connects to whatever Slack and Jira servers the user has installed.
- If a requested server isn't installed, startup logs explain: "Server 'jira' requested by mcp_registry.json but not installed. Run: hive mcp install jira"

### 4.5 Queen: Auto-Discovering Available MCP Servers

> As the queen agent, I want access to installed MCP servers so I can delegate tasks that require any tool.

**Acceptance criteria:**
- Queen's `mcp_registry.json` uses `{"profile": "all"}` to load all enabled servers.
- Startup logs list every loaded server and its tool count: "Loaded 3 registry servers: jira (4 tools), slack (6 tools), my-db (2 tools)"
- If tool names collide across servers, the resolution is deterministic and logged.
- Queen respects a configurable max tool budget to avoid prompt overload.

### 4.6 User: Diagnosing a Broken MCP Server

> As a user whose agent suddenly can't call Jira tools, I want to quickly find and fix the problem.

**Acceptance criteria:**
- `hive mcp doctor` checks all installed servers and reports: connection status, credential validity, tool discovery result, last error.
- `hive mcp doctor jira` gives detailed diagnostics: "jira: UNHEALTHY. Transport: stdio. Error: Process exited with code 1. Stderr: 'JIRA_API_TOKEN not set'. Fix: hive mcp config jira --set JIRA_API_TOKEN=your-token"
- `hive mcp inspect jira` shows the resolved config, override chain, and which agents include it.
- `hive mcp why-not jira --agent exports/my-agent` explains why a server was or was not loaded for an agent.

---

## 5. Requirements

### 5.1 Functional Requirements

#### 5.1.1 Registry Repository

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | The registry is a public GitHub repo with a defined directory structure for server entries | P0 |
| FR-2 | Each server entry is a `manifest.json` file conforming to a JSON Schema | P0 |
| FR-3 | CI validates manifests on every PR (schema, naming, uniqueness, required fields) | P0 |
| FR-4 | A flat index (`registry_index.json`) is auto-generated on merge for client consumption | P0 |
| FR-5 | A `_template/` directory provides a starter manifest + README for contributors | P0 |
| FR-6 | `CONTRIBUTING.md` documents the 5-minute submission process with annotated examples for each transport type (stdio, http, unix, sse) | P0 |
| FR-7 | CI checks that `install.pip` packages exist on PyPI (if specified) | P1 |
| FR-8 | Tags follow a controlled taxonomy with new tags requiring maintainer approval | P1 |
| FR-9 | Canonical example manifests are provided for each transport type in `registry/_examples/` | P0 |

#### 5.1.2 Manifest Schema

The manifest has a **portable base layer** (framework-agnostic, usable by any MCP client) and an optional **hive extension block** (Hive-specific ergonomics).

| ID | Requirement | Priority |
|---|---|---|
| FR-10 | Manifest base includes: name, display_name, version, description, author, repository, license | P0 |
| FR-11 | Manifest declares supported transports (stdio, http, unix, sse) with default | P0 |
| FR-12 | Manifest includes install instructions (pip package name, docker image, npm package) | P0 |
| FR-13 | Manifest lists tool names and descriptions (for pre-connect filtering) | P0 |
| FR-14 | Manifest declares credential requirements (env_var, description, help_url, required flag) | P0 |
| FR-15 | Manifest includes tags and categories for discovery | P1 |
| FR-16 | Manifest supports template variables (`{port}`, `{socket_path}`, `{name}`) in commands | P1 |
| FR-17 | Manifest includes `hive` extension block for Hive-specific metadata (see 5.1.8) | P1 |

#### 5.1.3 Manifest Trust & Quality Metadata

| ID | Requirement | Priority |
|---|---|---|
| FR-80 | Manifest includes `status` field: `official`, `verified`, or `community` | P0 |
| FR-81 | Manifest includes `maintainer` contact (email or GitHub handle) | P0 |
| FR-82 | Manifest includes `docs_url` pointing to server documentation | P1 |
| FR-83 | Manifest includes `example_agent_url` linking to an example agent using this server | P2 |
| FR-84 | Manifest includes `supported_os` list (e.g., `["linux", "macos", "windows"]`) | P1 |
| FR-85 | Manifest includes `deprecated` boolean and `deprecated_by` field for superseded entries | P1 |
| FR-86 | Registry index includes `last_validated_at` timestamp per entry (from automated CI health runs) | P1 |

#### 5.1.4 Local Registry

| ID | Requirement | Priority |
|---|---|---|
| FR-20 | `~/.hive/mcp_registry/installed.json` tracks all installed/registered servers | P0 |
| FR-21 | Servers can be sourced from the remote registry (`"source": "registry"`) or local (`"source": "local"`) | P0 |
| FR-22 | Each installed server has: transport preference, enabled/disabled state, and env/header overrides | P0 |
| FR-23 | The remote registry index is cached locally with configurable refresh interval | P1 |
| FR-24 | Each installed server tracks operational state: `last_health_check_at`, `last_health_status`, `last_error`, `last_used_at`, `resolved_package_version` | P1 |
| FR-25 | Each installed server supports `pinned: true` to prevent auto-update and `auto_update: true` for automatic version tracking | P1 |

#### 5.1.5 CLI Commands — Management

| ID | Requirement | Priority |
|---|---|---|
| FR-30 | `hive mcp install <name> [--version X]` — install from registry, optionally pin version | P0 |
| FR-31 | `hive mcp add --name X --transport T --url U` — register a local server | P0 |
| FR-32 | `hive mcp add --from manifest.json` — register from a manifest file | P1 |
| FR-33 | `hive mcp remove <name>` — uninstall/unregister | P0 |
| FR-34 | `hive mcp list` — list installed servers with status, health, and trust tier | P0 |
| FR-35 | `hive mcp list --available` — list all servers in remote registry | P1 |
| FR-36 | `hive mcp search <query>` — search by name/tag/description/tool-name | P1 |
| FR-37 | `hive mcp enable/disable <name>` — toggle without removing | P0 |
| FR-38 | `hive mcp health [name]` — check server reachability and tool discovery | P1 |
| FR-39 | `hive mcp update [name]` — refresh index cache or update a specific server | P1 |
| FR-40 | `hive mcp config <name> --set KEY=VAL` — set credential/env overrides | P0 |
| FR-41 | `hive mcp info <name>` — show full details: trust tier, version, tools, health, which agents use it | P0 |

#### 5.1.6 CLI Commands — Contributor Tooling

| ID | Requirement | Priority |
|---|---|---|
| FR-42 | `hive mcp init [--server-url URL]` — scaffold a manifest; if URL provided, introspects server to pre-fill tools list | P0 |
| FR-43 | `hive mcp validate <path>` — validate a manifest against the JSON Schema locally | P0 |
| FR-44 | `hive mcp test <path>` — start the server per manifest config, list tools, run health check, report pass/fail | P1 |

#### 5.1.7 CLI Commands — Diagnostics

| ID | Requirement | Priority |
|---|---|---|
| FR-45 | `hive mcp doctor [name]` — check all or one server: connection, credentials, tool discovery, last error; output actionable fix suggestions | P0 |
| FR-46 | `hive mcp inspect <name>` — show resolved config including override chain, transport details, and which agents include/exclude this server | P1 |
| FR-47 | `hive mcp why-not <name> --agent <path>` — explain why a server was or was not loaded for a specific agent's `mcp_registry.json` | P1 |

#### 5.1.8 Hive Extension Block in Manifest

The optional `hive` block in the manifest carries Hive-specific metadata that doesn't belong in the portable base:

| ID | Requirement | Priority |
|---|---|---|
| FR-90 | `hive.min_version` — minimum Hive version required | P1 |
| FR-91 | `hive.max_version` — maximum compatible Hive version (optional, for deprecation) | P2 |
| FR-92 | `hive.example_agent` — path or URL to an example agent using this server | P2 |
| FR-93 | `hive.profiles` — list of profile tags this server belongs to (e.g., `["core", "productivity", "developer"]`) | P1 |
| FR-94 | `hive.tool_namespace` — optional prefix for tool names to avoid collisions (e.g., `jira_`) | P1 |

#### 5.1.9 Agent Selection

| ID | Requirement | Priority |
|---|---|---|
| FR-50 | Agents can declare MCP server preferences in `mcp_registry.json` | P0 |
| FR-51 | Selection supports: explicit `include` list, `tags` matching, `exclude` blacklist | P0 |
| FR-52 | `profile` field loads servers matching a named profile (e.g., `"all"`, `"core"`, `"productivity"`) | P0 |
| FR-53 | If `mcp_registry.json` does not exist, no registry servers are loaded (backward compatible) | P0 |
| FR-54 | Missing requested servers produce warnings with actionable install instructions, not errors | P0 |
| FR-55 | Agent startup logs a summary of loaded/skipped registry servers with reasons | P0 |
| FR-56 | `max_tools` field caps total tools loaded from registry servers (prevents prompt overload) | P1 |

#### 5.1.10 Tool Resolution & Namespacing

| ID | Requirement | Priority |
|---|---|---|
| FR-100 | When multiple servers expose a tool with the same name, the first server in include-order wins (deterministic) | P0 |
| FR-101 | Tool collisions are logged at startup: "Tool 'search' from 'brave-search' shadowed by 'google-search' (loaded first)" | P0 |
| FR-102 | If a server declares `hive.tool_namespace`, its tools are prefixed: `jira_create_issue` instead of `create_issue` | P1 |
| FR-103 | `hive mcp inspect <name>` shows which tools are active vs shadowed | P1 |

#### 5.1.11 Connection Management

| ID | Requirement | Priority |
|---|---|---|
| FR-60 | A process-level connection manager shares MCP connections across agents | P1 |
| FR-61 | Connections are reference-counted — disconnected when no agent uses them | P1 |
| FR-62 | HTTP/unix/SSE connections retry once on failure before raising an error | P1 |

#### 5.1.12 Transport Extensions

| ID | Requirement | Priority |
|---|---|---|
| FR-70 | `MCPClient` supports unix socket transport via `httpx` UDS | P1 |
| FR-71 | `MCPClient` supports SSE transport via the official MCP Python SDK | P1 |
| FR-72 | `MCPServerConfig` includes `socket_path` field for unix transport | P1 |

### 5.2 Version Compatibility & Upgrade Safety

| ID | Requirement | Priority |
|---|---|---|
| VC-1 | Manifest includes `version` (semver) for the registry entry and `mcp_protocol_version` for the MCP spec | P0 |
| VC-2 | Manifest `hive` block includes optional `min_version` / `max_version` constraints | P1 |
| VC-3 | `hive mcp install` installs latest by default; `--version X` pins a specific version | P0 |
| VC-4 | `installed.json` records `resolved_package_version` (actual pip/npm version installed) | P1 |
| VC-5 | `hive mcp update <name>` compares old and new tool lists; warns if tools were removed or signatures changed | P1 |
| VC-6 | Agents can pin a resolved server version in `mcp_registry.json` via `"versions": {"jira": "1.2.0"}` | P2 |
| VC-7 | If a pinned version is no longer available, the agent logs an error with rollback instructions | P2 |
| VC-8 | `hive mcp update --dry-run` shows what would change without applying | P1 |
| VC-9 | Tool names and parameter schemas from the manifest constitute a compatibility contract; breaking changes require a major version bump | P1 |

### 5.3 Failure Handling & Diagnostics

| ID | Requirement | Priority |
|---|---|---|
| DX-1 | All MCP errors use structured error codes (e.g., `MCP_INSTALL_FAILED`, `MCP_AUTH_MISSING`, `MCP_CONNECT_TIMEOUT`, `MCP_TOOL_NOT_FOUND`, `MCP_PROTOCOL_MISMATCH`) | P0 |
| DX-2 | Every error message includes: what failed, why, and a suggested fix command | P0 |
| DX-3 | `hive mcp doctor` checks: connection, credentials (are required env vars set?), tool discovery, protocol version compatibility, Hive version compatibility | P0 |
| DX-4 | Agent startup emits a structured log line per registry server: `{server, status, tools_loaded, skipped_reason}` | P0 |
| DX-5 | Failed tool calls from registry servers include the server name and transport in the error context | P1 |
| DX-6 | `hive mcp doctor` output is machine-parseable (JSON with `--json` flag) for CI/automation | P2 |

### 5.4 Non-Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| NFR-1 | Registry index fetch must complete in <5s on typical internet connections | P1 |
| NFR-2 | Installing a server from registry must not require a Hive restart | P0 |
| NFR-3 | Connection manager must be thread-safe (multiple agents in same process) | P0 |
| NFR-4 | All new code must have unit test coverage | P0 |
| NFR-5 | Registry repo CI must run in <60s | P1 |
| NFR-6 | Manifest base schema must be framework-agnostic (usable by non-Hive MCP clients); Hive-specific fields live in the `hive` extension block | P1 |
| NFR-7 | `hive mcp install` prints a security notice on first use: "Registry servers run code on your machine. Only install servers you trust." | P0 |

---

## 6. Architecture Overview

```
                        ┌──────────────────────────────────┐
                        │    hive-mcp-registry (GitHub)     │
                        │                                    │
                        │  registry/servers/jira/manifest    │
                        │  registry/servers/slack/manifest   │
                        │  ...                               │
                        │  registry_index.json (auto-built)  │
                        └────────────────┬───────────────────┘
                                         │  hive mcp update
                                         │  (fetches index)
                                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ~/.hive/mcp_registry/                          │
│                                                                      │
│  installed.json          config.json          cache/                 │
│  (jira, slack,           (preferences)        registry_index.json   │
│   my-custom-db)                               (cached remote)       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────────┐
              │               │                   │
              ▼               ▼                   ▼
     ┌─────────────┐  ┌─────────────┐   ┌──────────────┐
     │ Queen Agent  │  │Worker Agent │   │ hive mcp CLI │
     │              │  │             │   │              │
     │ mcp_registry │  │mcp_registry │   │ install      │
     │ .json:       │  │.json:       │   │ add / remove │
     │ profile: all │  │include:     │   │ doctor       │
     │              │  │  [jira]     │   │ init / test  │
     └──────┬───────┘  └──────┬──────┘   └──────────────┘
            │                 │
            ▼                 ▼
     ┌──────────────────────────────────┐
     │       MCPConnectionManager       │
     │       (process singleton)        │
     │                                   │
     │  jira → MCPClient (stdio, rc=2)  │
     │  slack → MCPClient (http, rc=1)  │
     │  my-db → MCPClient (unix, rc=1)  │
     └──────────────────────────────────┘
            │          │          │
            ▼          ▼          ▼
     ┌──────────┐ ┌────────┐ ┌────────────┐
     │ Jira MCP │ │Slack   │ │ Custom DB  │
     │ (stdio)  │ │MCP     │ │ MCP (unix  │
     │          │ │(http)  │ │  socket)   │
     └──────────┘ └────────┘ └────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| **hive-mcp-registry** (GitHub repo) | Curated index of MCP server manifests; CI validates PRs; automated health checks |
| **~/.hive/mcp_registry/** | Local state: installed servers, cached index, user config, operational telemetry |
| **MCPRegistry** (Python module) | Core logic: install, remove, search, resolve for agent, doctor |
| **MCPConnectionManager** | Process-level connection pool with refcounting |
| **MCPClient** (extended) | Adds unix socket, SSE transports; retry on failure |
| **ToolRegistry** (extended) | New `load_registry_servers()` method with collision handling |
| **AgentRunner** (extended) | Loads `mcp_registry.json` alongside `mcp_servers.json`; logs resolution summary |
| **hive mcp CLI** | User-facing commands for management, diagnostics, and contributor tooling |

---

## 7. Data Models

### 7.1 Registry Manifest (`manifest.json`)

```json
{
  "$schema": "https://raw.githubusercontent.com/aden-hive/hive-mcp-registry/main/schema/manifest.schema.json",

  "name": "jira",
  "display_name": "Jira MCP Server",
  "version": "1.2.0",
  "description": "Interact with Jira issues, boards, and sprints",
  "author": {"name": "Jane Contributor", "github": "janedev", "url": "https://github.com/janedev"},
  "maintainer": {"github": "janedev", "email": "jane@example.com"},
  "repository": "https://github.com/janedev/jira-mcp-server",
  "license": "MIT",
  "status": "community",
  "docs_url": "https://github.com/janedev/jira-mcp-server/blob/main/README.md",
  "supported_os": ["linux", "macos", "windows"],
  "deprecated": false,

  "transport": {"supported": ["stdio", "http"], "default": "stdio"},
  "install": {"pip": "jira-mcp-server", "docker": "ghcr.io/janedev/jira-mcp-server:latest", "npm": null},

  "stdio": {"command": "uvx", "args": ["jira-mcp-server", "--stdio"]},
  "http": {"default_port": 4010, "health_path": "/health", "command": "uvx", "args": ["jira-mcp-server", "--http", "--port", "{port}"]},
  "unix": {"socket_template": "/tmp/mcp-{name}.sock", "command": "uvx", "args": ["jira-mcp-server", "--unix", "{socket_path}"]},

  "tools": [
    {"name": "jira_create_issue", "description": "Create a new Jira issue"},
    {"name": "jira_search", "description": "Search Jira issues with JQL"},
    {"name": "jira_update_issue", "description": "Update an existing issue"},
    {"name": "jira_list_boards", "description": "List all Jira boards"}
  ],

  "credentials": [
    {"id": "jira_api_token", "env_var": "JIRA_API_TOKEN", "description": "Jira API token", "help_url": "https://id.atlassian.com/manage-profile/security/api-tokens", "required": true},
    {"id": "jira_domain", "env_var": "JIRA_DOMAIN", "description": "Your Jira domain (e.g., mycompany.atlassian.net)", "required": true}
  ],

  "tags": ["project-management", "atlassian", "issue-tracking"],
  "categories": ["productivity"],
  "mcp_protocol_version": "2024-11-05",

  "hive": {
    "min_version": "0.5.0",
    "max_version": null,
    "profiles": ["productivity", "developer"],
    "tool_namespace": "jira",
    "example_agent": "https://github.com/janedev/jira-mcp-server/tree/main/examples/hive-agent"
  }
}
```

**Schema layering**:
- Everything outside `hive` is the **portable base** — usable by any MCP client.
- The `hive` block carries Hive-specific compatibility, profiles, namespacing, and examples.

### 7.2 Agent Selection (`mcp_registry.json`)

```json
{
  "include": ["jira", "slack"],
  "tags": ["crm"],
  "exclude": ["github"],
  "profile": "productivity",
  "max_tools": 50,
  "versions": {
    "jira": "1.2.0"
  }
}
```

**Selection precedence** (deterministic):
1. `profile` expands to a set of server names (union with `include` + `tags` matches).
2. `include` adds explicit servers.
3. `tags` adds servers whose tags overlap.
4. `exclude` removes from the final set (always wins).
5. Servers are loaded in `include`-order first, then alphabetically for tag/profile matches.
6. Tool collisions resolved by load order: first server wins.

### 7.3 Installed Server Entry (`installed.json` → `servers.<name>`)

```json
{
  "source": "registry",
  "manifest_version": "1.2.0",
  "manifest": {},
  "installed_at": "2026-03-13T10:00:00Z",
  "installed_by": "hive mcp install",
  "transport": "stdio",
  "enabled": true,
  "pinned": false,
  "auto_update": false,
  "resolved_package_version": "1.2.0",
  "overrides": {"env": {"JIRA_DOMAIN": "mycompany.atlassian.net"}, "headers": {}},
  "last_health_check_at": "2026-03-13T12:00:00Z",
  "last_health_status": "healthy",
  "last_error": null,
  "last_used_at": "2026-03-13T11:30:00Z",
  "last_validated_with_hive_version": "0.6.0"
}
```

---

## 8. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Low contributor adoption — nobody submits servers | Registry is empty, no value delivered | Medium | Seed with 5-10 popular MCP servers; `hive mcp init` makes submission trivial; canonical examples for every transport |
| High support burden from low-quality entries | Users install broken servers, file tickets against Hive | Medium | Trust tiers (official/verified/community); automated health checks in registry CI; `hive mcp doctor` for self-service debugging; quality gates beyond schema validation |
| Malicious MCP server in registry | User installs server that exfiltrates data or executes harmful code | Low | Maintainer review on all PRs; security notice on first install; servers run in user's trust boundary; verified tier requires code audit |
| Breaking changes to manifest schema | Existing manifests become invalid | Low | Schema versioning with `$schema` URL; CI validates backward compatibility; migration scripts |
| Server upgrades silently break agents | Tool signatures change, agents fail at runtime | Medium | `hive mcp update` diffs tool lists and warns on breaking changes; version pinning in `mcp_registry.json`; `--dry-run` flag |
| Connection manager concurrency bugs | Tool calls fail or deadlock under load | Medium | Thorough unit tests; reuse existing thread-safety patterns from `MCPClient._stdio_call_lock` |
| Registry index URL becomes unavailable | Users can't install new servers | Low | Local cache with TTL; fallback to last-known-good index; registry is a static file (cheap to host/mirror) |
| Name squatting in registry | Bad actors claim popular names | Low | Maintainer review on all PRs; naming guidelines in CONTRIBUTING.md |
| Auto-discover overloads agents with too many tools | Prompt bloat, confused tool selection, slower responses | Medium | `max_tools` cap in `mcp_registry.json`; profiles instead of blanket auto-discover; startup log shows tool count |
| Tool name collisions across servers | Wrong server handles a tool call | Medium | Deterministic load-order resolution; startup collision logging; optional tool namespacing via `hive.tool_namespace` |

---

## 9. Backward Compatibility

This system is **fully additive**:

- Existing `mcp_servers.json` files continue to work unchanged.
- Agents without `mcp_registry.json` load zero registry servers.
- The `MCPConnectionManager` is only used for registry-sourced connections; existing direct `MCPClient` usage is untouched.
- New CLI commands (`hive mcp ...`) don't conflict with existing commands.
- No existing files are modified in a breaking way.
- `mcp_servers.json` tools always take precedence over registry tools (they load first).

---

## 10. Documentation & Examples Strategy

Documentation is a first-class deliverable, not an afterthought. The following are required for launch:

| Doc | Audience | Deliverable |
|---|---|---|
| "Publish your first MCP server" | Contributors | Step-by-step guide from zero to merged registry entry, with screenshots |
| "Install and use your first registry server" | Users | Guide from `hive mcp install` to agent tool call |
| "Migration from mcp_servers.json" | Existing users | How to move static configs to registry-based selection |
| "Troubleshooting MCP servers" | Users | Common errors, `doctor` output examples, fix recipes |
| Manifest cookbook | Contributors | Annotated examples for stdio, http, unix, sse, multi-credential, no-credential |
| Example agents | Agent builders | 2-3 sample agents using `mcp_registry.json` with different selection strategies |

---

## 11. Phased Delivery

| Phase | Scope | Depends On |
|---|---|---|
| **Phase 1: Foundation** | MCPClient transport extensions (unix, SSE, retry); MCPConnectionManager; MCPRegistry module; CLI management commands; ToolRegistry `load_registry_servers()` with collision handling; AgentRunner `mcp_registry.json` loading with startup logging; structured error codes | -- |
| **Phase 2: Developer Tooling** | `hive mcp init`, `validate`, `test` (contributor flow); `doctor`, `inspect`, `why-not` (diagnostics); version pinning and `update --dry-run` | Phase 1 |
| **Phase 3: Registry Repo** | Create `hive-mcp-registry` GitHub repo with schema, validation CI, template, examples, CONTRIBUTING.md; seed with reference entries for built-in servers; automated health check CI | Phase 1 |
| **Phase 4: Docs & Launch** | All documentation deliverables from section 10; example agents; announcement | Phase 2, 3 |
| **Phase 5: Community Growth** | Trust tier promotion process; curated starter packs; popular/trending signals in registry | Phase 4 |
| **Phase 6: Monolith Decomposition** (future) | Extract tool groups from `mcp_server.py` into standalone servers; each becomes a registry entry | Phase 5 |

---

## 12. Open Questions

| # | Question | Owner | Status |
|---|---|---|---|
| Q1 | Should the registry repo live under `aden-hive` org or a new `hive-mcp` org? | Platform team | Open |
| Q2 | Should `hive mcp install` auto-prompt for required credentials interactively? | UX | Open |
| Q3 | Should the connection manager have a configurable max concurrent connections limit? | Engineering | Open |
| Q4 | Should we support a `docker` transport (Hive manages container lifecycle)? | Engineering | Open |
| Q5 | What is the process for promoting a `community` entry to `verified`? (e.g., code audit, usage threshold, maintainer SLA) | Platform + Security | Open |
| Q6 | Should the registry support private/enterprise indexes (e.g., `hive mcp config --index-url https://internal/...`)? | Platform | Open |
| Q7 | Should `hive mcp doctor` report telemetry (opt-in) to help identify systemic issues? | Product + Privacy | Open |
| Q8 | How should we handle MCP servers that require OAuth flows (not just static API keys)? | Engineering | Open |

---

## 13. Stakeholder Sign-Off

| Role | Name | Status |
|---|---|---|
| Engineering Lead | | Pending |
| Product | | Pending |
| OSS / Community | | Pending |
| Security | | Pending |
| Developer Experience | | Pending |
