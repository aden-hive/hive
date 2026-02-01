# Fix: Register function nodes from agent's tools.py at runtime

## Issue

Fixes the runtime failure when running exported agents that use **function** nodes. Without this fix, execution fails with:

- `RuntimeError: Function node 'X' not registered. Register with node_registry.`
- or `'function' object has no attribute 'validate_input'` if a raw callable is passed.

**Issue:** [#function-nodes-not-registered-at-runtime](../issues/function-nodes-not-registered-at-runtime.md)

## Summary

The runner only used the agent’s `tools.py` for **LLM tools** (via `ToolRegistry`). It never built a **function node registry** for graph nodes with `node_type == "function"`, so `GraphExecutor` had no implementation for those nodes and failed when it reached them.

This PR:

1. **Runner** – Adds `_build_function_node_registry()` that loads the agent’s `tools.py`, finds every graph node with `node_type == "function"`, resolves `node_spec.function` to a callable in that module, wraps it in `FunctionNode`, and returns `node_id -> FunctionNode(callable)`.
2. **Runner** – Uses that registry when creating the executor (legacy path) and when creating the agent runtime (multi-entry-point path).
3. **AgentRuntime / ExecutionStream** – Threads an optional `node_registry` through `create_agent_runtime`, `AgentRuntime`, and `ExecutionStream` so multi-entry-point runs get the same function-node implementations.

## Changes

| Area | Change |
|------|--------|
| `core/framework/runner/runner.py` | Add `_build_function_node_registry()`; pass `node_registry` into `GraphExecutor` and `create_agent_runtime()`. |
| `core/framework/runtime/agent_runtime.py` | Add `node_registry` to `AgentRuntime.__init__` and `create_agent_runtime()`; pass to `ExecutionStream`. |
| `core/framework/runtime/execution_stream.py` | Add `node_registry` to `ExecutionStream.__init__`; pass to `GraphExecutor`. |

## Reproduction / verification

1. Create an export with function nodes (e.g. `core/exports/greeting-agent/` with `agent.json` + `tools.py` containing `greet` and `uppercase` as in the issue).
2. Run:  
   `python -m framework run exports/greeting-agent --input '{"name": "Alice"}' --quiet`
3. **Before fix:** Fails with `RuntimeError` or `'function' object has no attribute 'validate_input'`.
4. **After fix:** Succeeds with `"success": true` and `"output": { "final_greeting": "HELLO, ALICE!" }`.

All existing tests pass (`pytest tests/ framework/runtime/tests/`).

## Checklist

- [x] Issue documented with reproduction steps
- [x] Fix implemented (runner + runtime threading)
- [x] Legacy single-entry and multi-entry paths both use the registry
- [x] All 229 tests pass
- [x] Manual run of exported function-node agent succeeds
