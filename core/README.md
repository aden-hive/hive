# Core Framework

The core runtime that powers Hive [colonies of agents](../docs/key_concepts/colony.md): the `AgentLoop` primitive, the `ColonyRuntime`, the Queen/worker model, and the HTTP server + CLI that drive them.

## Overview

Hive has a single execution primitive — the **`AgentLoop`** (`framework/agent_loop/agent_loop.py`), a multi-turn streaming LLM loop. A **Queen** is a long-lived `AgentLoop`; every **worker** is a bounded clone of it. The **`ColonyRuntime`** (`framework/host/colony_runtime.py`) spawns and schedules those clones and collects their results. There are no graphs, nodes, or edges — a colony coordinates through a shared SQLite **tracker**, a persistent **task plan**, an **event bus**, and a **reminder hub**.

For the full design, read the **[Architecture Overview](../docs/architecture/README.md)** and the [key concepts](../docs/key_concepts/colony.md).

## Setup

Hive uses a `uv` workspace layout and is **not** installed with `pip install`. Use the quickstart from the repo root:

```bash
./quickstart.sh          # macOS/Linux
.\quickstart.ps1         # Windows (PowerShell)
```

This creates the framework venv (`core/.venv`), the tools venv (`tools/.venv`), and the encrypted credential store, then opens the dashboard.

## Running

Everything runs through the `hive` CLI (from the project root):

```bash
hive open                          # start the server and open the dashboard
hive serve --port 8787             # start the HTTP API server only

hive queen list                    # list the built-in Queen personas
hive queen show <queen_id>         # inspect a Queen profile
hive queen sessions <queen_id>     # list a Queen's sessions

hive colony list                   # list colonies on disk
hive colony info <name>            # inspect a colony (tracker, workers, plan)
hive colony delete <name>          # delete a colony

hive session list [--cold]         # list live (or on-disk) sessions
hive session stop <session_id>     # stop a live session
hive chat <session_id> "message"   # send a message to a live Queen
```

Subsystems: `hive skill ...` (manage skills), `hive mcp ...` (manage MCP servers), `hive debugger` (LLM debug log viewer). Run `hive --help` for the full list.

## On-disk layout (`HIVE_HOME`)

State lives under `HIVE_HOME` (defaults to the platform app-data dir; override with the `HIVE_HOME` env var):

```
$HIVE_HOME/
  agents/queens/<queen_id>/     # Queen profiles + sessions
  colonies/<name>/              # one directory per colony
    worker.json                 #   the colony's worker spec (clone template)
    data/tracker.db             #   the colony's shared SQLite ledger
  memories/                     # scoped Queen memory (global / colony / queen)
  credentials/                  # encrypted credential store
```

A colony is self-contained in its directory, which is what makes it portable (export/import as a tarball).

## Key modules

| Area | Path |
| --- | --- |
| Agent loop (the one primitive) | `framework/agent_loop/agent_loop.py` |
| Colony runtime (spawn/schedule/collect) | `framework/host/colony_runtime.py`, `framework/host/worker.py` |
| Colony identity/binding | `framework/host/colony_binding.py` |
| Queen (agent, personas, phases, memory) | `framework/agents/queen/` |
| Tracker (shared ledger) | `framework/tools/tracker_tools.py`, `framework/host/tracker_db.py` |
| Task plan | `framework/tasks/` |
| Reminder hub | `framework/agent_loop/reminders.py` |
| LLM providers | `framework/llm/` |
| HTTP server / control plane | `framework/server/` |

## Requirements

- Python 3.11+
- An LLM provider (Anthropic, OpenAI, Google Gemini, OpenRouter, Hive LLM, or any LiteLLM-compatible provider — including local models via Ollama)

## Testing

The framework includes a goal-based testing harness for validating agent behavior. See the [Developer Guide](../docs/developer-guide.md) for workflows.
