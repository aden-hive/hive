# Worker Health Monitoring

Automatic health monitoring for worker agents running in the TUI. Three components share one runtime and one EventBus: the worker, the Health Judge, and the Queen. No agent-side configuration is required.

## The Problem

The previous approach used a guardian subgraph attached to hive_coder's runtime to monitor worker agents. It had two failure modes:

1. **Never fired.** Worker agents run in their own TUI context with their own `AgentRuntime` and therefore their own `EventBus`. hive_coder's guardian subscribed to hive_coder's bus, which never received worker events.
2. **Too trigger-happy.** When a worker was loaded into the same runtime (e.g., via `add_graph`), the guardian fired on `EXECUTION_FAILED` — a single hard failure event. It could not distinguish "agent is genuinely broken" from "agent is momentarily waiting for user input". `exclude_own_graph: False` also caused it to fire on hive_coder's own events.

The root cause: reactive event-based monitoring on binary hard-failure events cannot reason about degradation patterns.

## Architecture

Three graphs run on one `AgentRuntime` (one `EventBus`) when a worker is loaded:

```
AgentRuntime (shared EventBus)
│
├── Worker Graph (primary)
│   └── EventLoopNode — does the actual work
│       └── writes per-step logs to sessions/{id}/logs/tool_logs.jsonl
│
├── Health Judge Graph (secondary, timer-driven)
│   └── Entry point: timer every 2 min → judge node (event_loop)
│       ├── calls get_worker_health_summary() — auto-discovers active session
│       ├── compares total_steps to previous check (via conversation history)
│       ├── detects: excessive RETRYs, stall, doom loop
│       └── if degraded: calls emit_escalation_ticket(ticket_json)
│           → publishes WORKER_ESCALATION_TICKET on shared EventBus
│
└── Queen Graph (secondary, event-driven)
    └── Entry point: fires on WORKER_ESCALATION_TICKET
        ├── ticket_triage_node reads the ticket from memory
        ├── LLM applies dismiss/intervene criteria
        └── if intervening: calls notify_operator(ticket_id, analysis, urgency)
            → publishes QUEEN_INTERVENTION_REQUESTED on shared EventBus

TUI
├── subscribes to QUEEN_INTERVENTION_REQUESTED
├── shows non-disruptive notification (worker NOT paused)
└── Ctrl+Q → switches chat pane to queen's graph view
```

**Key invariant**: all three are loaded on the same `AgentRuntime` object. They cannot have separate EventBuses. There is no inter-process communication.

## Loading

The TUI loads the judge and queen automatically in `_finish_agent_load` for any agent whose name is not `hive_coder`:

```python
if agent_name != "hive_coder":
    await self._load_judge_and_queen(runner._storage_path)
```

`_load_judge_and_queen` does three things:

1. Registers monitoring tools (`get_worker_health_summary`, `emit_escalation_ticket`, `notify_operator`) bound to the worker's `EventBus` and `storage_path`.
2. Merges those tools into `runtime._tools` / `runtime._tool_executor` so secondary graph streams can call them.
3. Calls `runtime.add_graph()` twice — once for the judge, once for the queen.

## Session Auto-Discovery

`get_worker_health_summary` does not require a `session_id` argument. If omitted (or `"auto"`), it scans `storage_path/sessions/` and selects the most recent in-progress session by directory mtime. This means the judge can start monitoring immediately after the first worker execution begins, with zero configuration.

```python
# On first health check, judge calls with no arguments:
get_worker_health_summary()

# The tool finds the active session automatically and returns:
{
  "session_id": "session_20260223_143022_abc12345",
  "total_steps": 12,
  "recent_verdicts": ["ACCEPT", "RETRY", "ACCEPT"],
  "steps_since_last_accept": 0,
  "stall_minutes": null,
  ...
}
```

The judge includes the discovered `session_id` in escalation tickets so the queen and operator can refer to it.

## The Judge

**File**: `core/framework/monitoring/worker_health_judge.py`

The judge is a proper `event_loop` NodeSpec — not inline Python code. Its reasoning is observable in the conversation history, tunable via system prompt, and conservative by design.

**Conversation mode**: `continuous` with `isolation_level="isolated"`. The conversation persists across timer ticks. The judge tracks trends by reading its own prior messages:

> "Last check: total_steps=47. This check: total_steps=47. Unchanged twice → stall confirmed."

**Escalation thresholds** (configurable via system prompt):

| Condition | Verdict |
|---|---|
| `steps_since_last_accept` < 5 | Healthy |
| 5–9 | Warning, no ticket |
| 10–14 | `medium` ticket if evidence shows loop |
| 15–19 | `high` ticket |
| ≥ 20, or stall ≥ 4 min | `critical` ticket |
| First check ever | No ticket (give worker time to start) |

**Tools available to judge**:
- `get_worker_health_summary([session_id])` — reads `tool_logs.jsonl`
- `emit_escalation_ticket(ticket_json)` — validates and publishes ticket

## The EscalationTicket

**File**: `core/framework/runtime/escalation_ticket.py`

Pydantic schema. All fields are required — partial tickets are rejected at validation time, preventing impulsive escalation.

```python
class EscalationTicket(BaseModel):
    ticket_id: str          # auto-generated UUID
    created_at: str         # auto-generated ISO timestamp

    worker_agent_id: str
    worker_session_id: str
    worker_node_id: str
    worker_graph_id: str

    severity: Literal["low", "medium", "high", "critical"]
    cause: str              # what the judge observed
    judge_reasoning: str    # why it decided to escalate
    suggested_action: str   # restart? human review? kill session?

    recent_verdicts: list[str]
    total_steps_checked: int
    steps_since_last_accept: int
    stall_minutes: float | None
    evidence_snippet: str   # last LLM output excerpt (≤500 chars)
```

## The Queen

**File**: `core/framework/agents/hive_coder/ticket_receiver.py` (entry point)
**Node**: `ticket_triage_node` in `core/framework/agents/hive_coder/nodes/__init__.py`

The queen is hive_coder's ticket-triage node loaded as a secondary graph. It provides a second quality gate: the judge may be overly sensitive; the queen applies a second filter before the operator is disturbed.

**Dismiss criteria** (do not notify operator):
- `severity == "low"` and `steps_since_last_accept < 8`
- Clearly transient issue (single timeout that self-resolved)
- Evidence shows genuine progress despite bad verdicts

**Intervene criteria** (call `notify_operator`):
- `severity in ("high", "critical")`
- `steps_since_last_accept >= 10` with no recovery sign
- `stall_minutes > 4`
- Evidence shows doom loop (same error, same tool, no new information)
- Logic bug or unrecoverable state

## New EventTypes

| Event | Emitter | Receiver | Data |
|---|---|---|---|
| `WORKER_ESCALATION_TICKET` | Health Judge (`emit_escalation_ticket`) | Queen ticket_receiver entry point | `{"ticket": EscalationTicket.model_dump()}` |
| `QUEEN_INTERVENTION_REQUESTED` | Queen (`notify_operator`) | TUI | `{"ticket_id", "analysis", "severity", "queen_graph_id", "queen_stream_id"}` |

## TUI Integration

**Ctrl+Q**: switch chat pane to queen's graph view. Only shown in footer when `_queen_graph_id` is set (i.e., when a worker with monitoring is loaded).

**WORKER_ESCALATION_TICKET**: updates status bar briefly (`judge: high ticket`). The worker keeps streaming normally.

**QUEEN_INTERVENTION_REQUESTED**: shows a 30-second dismissable notification with severity-colored label and the queen's analysis. Worker is NOT paused.

Both events are handled in the cross-graph filter (events from non-active graphs are normally silently dropped). These two are explicitly carved out to always surface.

## New Files

| File | Purpose |
|---|---|
| `core/framework/runtime/escalation_ticket.py` | `EscalationTicket` Pydantic schema |
| `core/framework/monitoring/__init__.py` | Package exports |
| `core/framework/monitoring/worker_health_judge.py` | Judge graph, node, goal, entry point |
| `core/framework/tools/worker_monitoring_tools.py` | `get_worker_health_summary`, `emit_escalation_ticket`, `notify_operator`; `register_worker_monitoring_tools()` |
| `core/framework/agents/hive_coder/ticket_receiver.py` | `TICKET_RECEIVER_ENTRY_POINT` for queen |

## Modified Files

| File | Changes |
|---|---|
| `core/framework/runtime/event_bus.py` | +2 `EventType` values, +2 emit methods |
| `core/framework/agents/hive_coder/nodes/__init__.py` | +`ticket_triage_node`, +`ALL_QUEEN_TRIAGE_TOOLS` |
| `core/framework/agents/hive_coder/agent.py` | +`ticket_triage_node` to nodes, +`TICKET_RECEIVER_ENTRY_POINT` to `async_entry_points` |
| `core/framework/tui/app.py` | +`_load_judge_and_queen()`, +`_handle_queen_intervention()`, +`action_connect_to_queen()`, +event routing, +binding |

## Known Gaps

**Gap 1 — Resolved.** The queen is now the full `HiveCoderAgent` graph (not a minimal hand-assembled subset). `_load_judge_and_queen` calls `HiveCoderAgent._setup(mock_mode=True)` to load hive-tools MCP, then merges those tools into the worker runtime alongside monitoring tools. When the operator connects via Ctrl+Q, they get `coder_node` with `read_file`, `write_file`, `run_command`, `restart_agent`, `get_agent_session_state`, and all other hive-tools. The `ticket_triage_node` still handles auto-triage on ticket events. `self._queen_agent` is held on the TUI instance to keep the MCP process alive.

**Gap 2 — LLM-hang detection latency.**
If the worker's LLM call hangs (API never returns), no new log entries are written. The judge detects this on its next timer tick (≤2 min). Bounded latency, not zero.

**Gap 3 — `worker_node_id` in tickets.**
`get_worker_health_summary` returns `worker_agent_id` (from `storage_path.name`) and `worker_graph_id` (from `runtime._graph_id`), so the judge can populate those ticket fields accurately. The `worker_node_id` field is set to `worker_graph_id` as a proxy — the judge has no way to know which specific node within the graph is currently executing. This is cosmetic: node identity is not used in triage logic.

**Gap 4 — Inter-runtime isolation.**
Judge and queen share the worker's EventBus only when loaded in the same runtime via `add_graph`. A separately-started hive_coder session in another TUI window is not connected.
