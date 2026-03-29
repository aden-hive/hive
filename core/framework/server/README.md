# Hive Server

HTTP API backend for the Hive agent framework. Built on **aiohttp**, fully async, serving the frontend workspace and external clients.

## Architecture

Sessions are the primary entity. A session owns an EventBus + LLM and always has a queen executor. Workers are optional — they can be loaded into and unloaded from a session at any time.

```
Session {
    event_bus       # owned by session, shared with queen + worker
    llm             # owned by session
    queen_executor  # always present
    worker_runtime? # optional — loaded/unloaded independently
}
```

## Structure

```
server/
├── app.py                 # Application factory, middleware, static serving
├── session_manager.py     # Session lifecycle (create/load worker/unload/stop)
├── sse.py                 # Server-Sent Events helper
├── routes_sessions.py     # Session lifecycle, info, worker-session browsing, discovery
├── routes_execution.py    # Trigger, inject, chat, stop, resume, replay
├── routes_events.py       # SSE event streaming
├── routes_graphs.py       # Graph topology & node inspection
├── routes_logs.py         # Execution logs (summary/details/tools)
├── routes_credentials.py  # Credential management & validation
├── routes_agents.py       # Legacy backward-compat routes
└── tests/
    └── test_api.py        # Full test suite with mocked runtimes
```

## Core Components

### `app.py` — Application Factory

`create_app(model)` builds the aiohttp `Application` with:

- **CORS middleware** — allows localhost origins
- **Error middleware** — catches exceptions, returns JSON errors
- **Static serving** — serves the frontend SPA with index.html fallback
- **Graceful shutdown** — stops all sessions on exit

### `session_manager.py` — Session Lifecycle Manager

Manages `Session` objects. Key methods:

- **`create_session()`** — creates EventBus + LLM, starts queen (no worker)
- **`create_session_with_worker()`** — one-step: session + worker + judge
- **`load_worker()`** — loads agent into existing session, starts judge
- **`unload_worker()`** — removes worker + judge, queen stays alive
- **`stop_session()`** — tears down everything (worker + queen)

Three-conversation model:
1. **Queen** — persistent interactive executor for user chat (always present)
2. **Worker** — `AgentRuntime` that executes graphs (optional)
3. **Judge** — timer-driven background executor for health monitoring (active when worker is loaded)

### `sse.py` — SSE Helper

Thin wrapper around `aiohttp.StreamResponse` for Server-Sent Events with keepalive pings.

## API Reference

All session-scoped routes use the `session_id` returned from `POST /api/sessions`.

### Discovery

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/discover` | Discover agents from filesystem |

Returns agents grouped by category with metadata (name, description, node count, tags, etc.).

### Session Lifecycle

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/sessions` | Create a session |
| `GET` | `/api/sessions` | List all active sessions |
| `GET` | `/api/sessions/{session_id}` | Session detail (includes entry points + graphs if worker loaded) |
| `DELETE` | `/api/sessions/{session_id}` | Stop session entirely |

**Create session** has two modes:

```jsonc
// Queen-only session (no worker)
POST /api/sessions
{}
// or with custom ID:
{ "session_id": "my-custom-id" }

// Session with worker (one-step)
POST /api/sessions
{
  "agent_path": "exports/my-agent",
  "agent_id": "custom-worker-name",  // optional
  "model": "claude-sonnet-4-20250514"      // optional
}
```

- Returns `201` with session object on success
- Returns `409` with `{"loading": true}` if agent is currently loading
- Returns `404` if agent_path doesn't exist

**Get session** returns `202` with `{"loading": true}` while loading, `404` if not found.

### Worker Lifecycle

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/sessions/{session_id}/worker` | Load a worker into session |
| `DELETE` | `/api/sessions/{session_id}/worker` | Unload worker (queen stays alive) |

```jsonc
// Load worker into existing session
POST /api/sessions/{session_id}/worker
{
  "agent_path": "exports/my-agent",
  "worker_id": "custom-name",  // optional
  "model": "..."               // optional
}

// Unload worker
DELETE /api/sessions/{session_id}/worker
```

### Execution Control

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/sessions/{session_id}/trigger` | Start a new execution |
| `POST` | `/api/sessions/{session_id}/inject` | Inject input into a waiting node |
| `POST` | `/api/sessions/{session_id}/chat` | Smart chat routing |
| `POST` | `/api/sessions/{session_id}/stop` | Cancel a running execution |
| `POST` | `/api/sessions/{session_id}/pause` | Alias for stop |
| `POST` | `/api/sessions/{session_id}/resume` | Resume a paused execution |
| `POST` | `/api/sessions/{session_id}/replay` | Re-run from a checkpoint |
| `GET` | `/api/sessions/{session_id}/goal-progress` | Evaluate goal progress |

**Trigger:**
```jsonc
POST /api/sessions/{session_id}/trigger
{
  "entry_point_id": "default",
  "input_data": { "query": "research topic X" },
  "session_state": {}  // optional
}
// Returns: { "execution_id": "..." }
```

**Chat** routes messages with priority:
1. Worker awaiting input -> inject into worker node
2. Queen active -> inject into queen conversation
3. Neither available -> 503

```jsonc
POST /api/sessions/{session_id}/chat
{ "message": "hello" }
// Returns: { "status": "injected"|"queen", "delivered": true }
```

**Inject** into a specific node:
```jsonc
POST /api/sessions/{session_id}/inject
{ "node_id": "gather_info", "content": "user response", "graph_id": "main" }
```

**Stop:**
```jsonc
POST /api/sessions/{session_id}/stop
{ "execution_id": "..." }
```

**Resume:**
```jsonc
POST /api/sessions/{session_id}/resume
{
  "session_id": "session_20260224_...",    // worker session to resume
  "checkpoint_id": "cp_..."               // optional — resumes from latest if omitted
}
```

**Replay** (re-run from checkpoint):
```jsonc
POST /api/sessions/{session_id}/replay
{
  "session_id": "session_20260224_...",
  "checkpoint_id": "cp_..."               // required
}
```

### SSE Event Streaming

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/sessions/{session_id}/events` | SSE event stream |

```
GET /api/sessions/{session_id}/events
GET /api/sessions/{session_id}/events?types=CLIENT_OUTPUT_DELTA,EXECUTION_COMPLETED
```

Keepalive ping every 15s. Streams from the session's EventBus (covers both queen and worker events).

Default event types: `CLIENT_OUTPUT_DELTA`, `CLIENT_INPUT_REQUESTED`, `LLM_TEXT_DELTA`, `TOOL_CALL_STARTED`, `TOOL_CALL_COMPLETED`, `EXECUTION_STARTED`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `EXECUTION_PAUSED`, `NODE_LOOP_STARTED`, `NODE_LOOP_ITERATION`, `NODE_LOOP_COMPLETED`, `NODE_ACTION_PLAN`, `EDGE_TRAVERSED`, `GOAL_PROGRESS`, `QUEEN_INTERVENTION_REQUESTED`, `WORKER_ESCALATION_TICKET`, `NODE_INTERNAL_OUTPUT`, `NODE_STALLED`, `NODE_RETRY`, `NODE_TOOL_DOOM_LOOP`, `CONTEXT_COMPACTED`, `WORKER_LOADED`.

### Session Info

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/sessions/{session_id}/stats` | Runtime statistics |
| `GET` | `/api/sessions/{session_id}/entry-points` | List entry points |
| `GET` | `/api/sessions/{session_id}/graphs` | List loaded graph IDs |

### Graph & Node Inspection

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/sessions/{session_id}/graphs/{graph_id}/nodes` | List nodes + edges |
| `GET` | `/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}` | Node detail + outgoing edges |
| `GET` | `/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/criteria` | Success criteria + last execution info |
| `GET` | `/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/tools` | Resolved tool metadata |

**List nodes** supports optional enrichment with session progress:
```
GET /api/sessions/{session_id}/graphs/{graph_id}/nodes?session_id=worker_session_id
```
Adds `visit_count`, `has_failures`, `is_current`, `in_path` to each node.

### Logs

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/sessions/{session_id}/logs` | Session-level logs |
| `GET` | `/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/logs` | Node-scoped logs |

```
# List recent runs
GET /api/sessions/{session_id}/logs?level=summary&limit=20

# Detailed per-node execution for a specific worker session
GET /api/sessions/{session_id}/logs?session_id=ws_id&level=details

# Tool call logs
GET /api/sessions/{session_id}/logs?session_id=ws_id&level=tools

# Node-scoped (requires session_id query param)
GET .../nodes/{node_id}/logs?session_id=ws_id&level=all
```

Log levels: `summary` (run stats), `details` (per-node execution), `tools` (tool calls + LLM text).

### Worker Session Browsing

Browse persisted execution runs on disk.

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/sessions/{session_id}/worker-sessions` | List worker sessions |
| `GET` | `/api/sessions/{session_id}/worker-sessions/{ws_id}` | Worker session state |
| `DELETE` | `/api/sessions/{session_id}/worker-sessions/{ws_id}` | Delete worker session |
| `GET` | `/api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints` | List checkpoints |
| `POST` | `/api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints/{cp_id}/restore` | Restore from checkpoint |
| `GET` | `/api/sessions/{session_id}/worker-sessions/{ws_id}/messages` | Get conversation messages |

**Messages** support filtering:
```
GET .../messages?node_id=gather_info      # filter by node
GET .../messages?client_only=true         # only user inputs + client-facing assistant outputs
```

### Credentials

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/credentials` | List credential metadata (no secrets) |
| `POST` | `/api/credentials` | Save a credential |
| `GET` | `/api/credentials/{credential_id}` | Get credential metadata |
| `DELETE` | `/api/credentials/{credential_id}` | Delete a credential |
| `POST` | `/api/credentials/check-agent` | Validate agent credentials |

**Save credential:**
```jsonc
POST /api/credentials
{ "credential_id": "brave_search", "keys": { "api_key": "BSA..." } }
```

**Check agent credentials** — two-phase validation (same as runtime startup):
```jsonc
POST /api/credentials/check-agent
{
  "agent_path": "exports/my-agent",
  "verify": true    // optional, default true — run health checks
}
// Returns:
{
  "required": [
    {
      "credential_name": "brave_search",
      "credential_id": "brave_search",
      "env_var": "BRAVE_SEARCH_API_KEY",
      "description": "Brave Search API key",
      "help_url": "https://...",
      "tools": ["brave_web_search"],
      "node_types": [],
      "available": true,
      "valid": true,              // true/false/null (null = not checked)
      "validation_message": "OK",  // human-readable health check result
      "direct_api_key_supported": true,
      "aden_supported": true,
      "credential_key": "api_key"
    }
  ]
}
```

When `verify: true`, runs health checks (lightweight HTTP calls) against each available credential to confirm it actually works — not just that it exists.

## Key Patterns

- **Session-primary** — sessions are the lookup key for all routes, workers are optional children
- **Per-request manager access** — routes get `SessionManager` via `request.app["manager"]`
- **Path validation** — user-provided path segments validated with `safe_path_segment()` to prevent directory traversal
- **Event-driven streaming** — per-client buffer queues (max 1000 events) with 15s keepalive pings
- **Shared EventBus** — session owns the bus, queen and worker both publish to it, SSE always connects to `session.event_bus`
- **No secrets in responses** — credential endpoints never return secret values

## Storage Paths

```
~/.hive/
├── queen/session/{session_id}/       # Queen conversation state
├── judge/session/{session_id}/       # Judge state
├── agents/{agent_name}/sessions/     # Worker execution sessions
└── credentials/                      # Encrypted credential store
```

## Running Tests

```bash
pytest framework/server/tests/ -v
```
