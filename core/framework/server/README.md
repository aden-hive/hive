# Hive Server

HTTP API backend for the Hive agent framework. Built on **aiohttp**, fully async, serving the frontend workspace and external clients.

## Structure

```
server/
├── app.py                 # Application factory, middleware, static serving
├── agent_manager.py       # Agent lifecycle (load/unload/monitor)
├── sse.py                 # Server-Sent Events helper
├── routes_agents.py       # Agent CRUD & discovery
├── routes_credentials.py  # Credential management
├── routes_execution.py    # Trigger, inject, chat, pause, resume, replay
├── routes_events.py       # SSE event streaming
├── routes_graphs.py       # Graph topology & node inspection
├── routes_logs.py         # Execution logs (summary/details/tools)
├── routes_sessions.py     # Session browsing & restore
└── tests/
    └── test_api.py        # Full test suite with mocked runtimes
```

## Core Components

### `app.py` — Application Factory

`create_app(model)` builds the aiohttp `Application` with:

- **CORS middleware** — allows localhost origins
- **Error middleware** — catches exceptions, returns JSON errors
- **Static serving** — serves the frontend SPA with index.html fallback
- **Graceful shutdown** — unloads all agents on exit

### `agent_manager.py` — Agent Lifecycle Manager

Manages `AgentSlot` objects — each holding a loaded agent's runtime resources:

- **`load_agent()`** — loads agent from disk, sets up runtime, starts queen + judge
- **`unload_agent()`** — cancels monitoring tasks, tears down runtime
- **Three-conversation model**:
  1. **Worker** — the existing `AgentRuntime` that executes graphs
  2. **Queen** — persistent interactive executor for user chat
  3. **Judge** — timer-driven background executor for health monitoring (fires every 2 min)

### `sse.py` — SSE Helper

Thin wrapper around `aiohttp.StreamResponse` for Server-Sent Events. Used by `routes_events.py` to stream runtime events to clients with keepalive pings.

## API Routes

### Agents — `/api/agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/discover` | Discover agents from filesystem |
| GET | `/api/agents` | List loaded agents |
| POST | `/api/agents` | Load agent (body: `agent_path`, `agent_id`, `model`) |
| GET | `/api/agents/{agent_id}` | Agent details + entry points + graphs |
| DELETE | `/api/agents/{agent_id}` | Unload agent |
| GET | `/api/agents/{agent_id}/stats` | Runtime statistics |

### Execution — `/api/agents/{agent_id}/...`

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../trigger` | Start new execution |
| POST | `.../inject` | Inject input to a waiting node |
| POST | `.../chat` | Smart routing: inject to worker/queen or trigger new |
| POST | `.../stop` | Cancel execution (saves as paused, resumable) |
| POST | `.../pause` | Alias for stop |
| POST | `.../resume` | Resume from session state or checkpoint |
| POST | `.../replay` | Re-run from a checkpoint |
| GET | `.../goal-progress` | Evaluate goal progress |

### Events — SSE Streaming

| Method | Path | Description |
|--------|------|-------------|
| GET | `.../events` | SSE stream (query: `types` for filtering) |

Default event types include: `CLIENT_OUTPUT_DELTA`, `CLIENT_INPUT_REQUESTED`, `EXECUTION_STARTED/COMPLETED/FAILED/PAUSED`, `NODE_LOOP_*`, `EDGE_TRAVERSED`, `GOAL_PROGRESS`, `QUEEN_INTERVENTION_REQUESTED`, and more.

### Graphs — Node Inspection

| Method | Path | Description |
|--------|------|-------------|
| GET | `.../graphs/{graph_id}/nodes` | List nodes (optional session enrichment) |
| GET | `.../graphs/{graph_id}/nodes/{node_id}` | Node detail + outgoing edges |
| GET | `.../graphs/{graph_id}/nodes/{node_id}/criteria` | Success criteria + judge verdicts |
| GET | `.../graphs/{graph_id}/nodes/{node_id}/tools` | Resolved tool metadata |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `.../sessions` | List all sessions |
| GET | `.../sessions/{session_id}` | Full session state |
| DELETE | `.../sessions/{session_id}` | Delete session |
| GET | `.../sessions/{session_id}/checkpoints` | List checkpoints |
| POST | `.../sessions/{session_id}/checkpoints/{checkpoint_id}/restore` | Restore checkpoint |
| GET | `.../sessions/{session_id}/messages` | Chat history (query: `node_id`, `client_only`) |

### Logs

| Method | Path | Description |
|--------|------|-------------|
| GET | `.../logs` | Agent-level logs (query: `session_id`, `level`, `limit`) |
| GET | `.../graphs/{graph_id}/nodes/{node_id}/logs` | Node-scoped logs |

Log levels: `summary` (run stats), `details` (per-node execution), `tools` (tool calls + LLM text).

### Credentials

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/credentials` | List credential metadata (no secrets) |
| POST | `/api/credentials` | Save credential |
| GET | `/api/credentials/{credential_id}` | Get credential metadata |
| DELETE | `/api/credentials/{credential_id}` | Delete credential |
| POST | `/api/credentials/check-agent` | Check which credentials an agent needs |

## Key Patterns

- **Per-request manager access** — routes get `AgentManager` via `request.app["manager"]`
- **Path validation** — all user-provided path segments validated with `safe_path_segment()` to prevent directory traversal
- **Event-driven streaming** — per-client buffer queues (max 1000 events) with 15s keepalive pings
- **Session persistence** — executions saved to `~/.hive/agents/{agent_name}/sessions/`
- **No secrets in responses** — credential endpoints never return secret values

## Running Tests

```bash
pytest core/framework/server/tests/ -v
```
