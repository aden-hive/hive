Visual Diff (TUI)
===================

Overview
--------

The Visual Diff feature displays topology and property-level differences when the
agent's graph is evolved. The TUI's `GraphOverview` widget enters diff mode on
`GRAPH_EVOLVED` events and can be toggled with `d`.

Keybindings
-----------
- `d` — toggle graph diff view
- `Up/Down` — navigate between modified nodes
- `Enter` — show a focused per-field diff for the selected node (old vs. new)

How it works
------------
- `OutcomeAggregator` may emit `GRAPH_EVOLUTION_REQUEST` when it recommends an
  adjustment.
- A Builder / CodingAgent may propose a candidate graph and call
  `AgentRuntime.update_graph(new_graph, correlation_id=...)`.
- `AgentRuntime` optionally runs an `EvolutionGuard` probation flow which
  snapshots, runs smoke/probation tests, and may approve or reject the candidate.
- If approved, `GRAPH_EVOLVED` is emitted containing `old_graph` and `new_graph`.
  The TUI renders a color-coded diff:
  - green `+` added nodes/edges
  - red `-` removed nodes/edges
  - yellow `~` modified nodes

Audit & Safety
--------------
- The runtime calls `evolution_guard.audit_log(...)` with a structured payload
  containing `snapshot_id`, `candidate_graph_id`, `result` and `correlation_id`.
- Audit entries are persisted to the runtime log store when available, otherwise
  they are written to `<storage_path>/evolution_audit/<id>.json` as a fallback.
