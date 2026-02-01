# Issue: Function nodes not registered at runtime when running exported agents

## Summary

When running an exported agent that uses **function** nodes (graph nodes with `node_type: "function"` and a `function` name pointing to a callable), the runner never registers those callables with the executor. Execution fails when it reaches a function node with:

```
RuntimeError: Function node 'greeter' not registered. Register with node_registry.
```

or, if a raw callable is passed without wrapping:

```
'function' object has no attribute 'validate_input'
```

## Why this is valuable

- **Supported workflow is broken:** The framework documents and supports `node_type: "function"` and provides `FunctionNode`; the manual agent example uses function nodes. Exporting such an agent and running it via the CLI/runner is a natural path, but it always fails. Fixing this makes exported agents with function nodes actually runnable.
- **High impact, contained fix:** Any exported agent that uses function nodes fails at runtime (complete failure, not a minor bug). The fix is scoped to the runner and runtime plumbing—no API break, no new surface area—so the payoff for maintainers and contributors is strong.

## Reproduction

### Prerequisites

- Python 3.11+, framework installed (`cd core && pip install -e . && pip install -r requirements-dev.txt`).
- No API keys required for a function-only agent.

### Steps

1. **Create an exported agent with function nodes**

   Create directory `core/exports/greeting-agent/` with:

   **`agent.json`**:

   ```json
   {
     "graph": {
       "id": "greeting-agent",
       "goal_id": "greet-user",
       "version": "1.0.0",
       "entry_node": "greeter",
       "terminal_nodes": ["uppercaser"],
       "nodes": [
         {
           "id": "greeter",
           "name": "Greeter",
           "description": "Generates a simple greeting",
           "node_type": "function",
           "function": "greet",
           "input_keys": ["name"],
           "output_keys": ["greeting"]
         },
         {
           "id": "uppercaser",
           "name": "Uppercaser",
           "description": "Converts greeting to uppercase",
           "node_type": "function",
           "function": "uppercase",
           "input_keys": ["greeting"],
           "output_keys": ["final_greeting"]
         }
       ],
       "edges": [
         {
           "id": "greet-to-upper",
           "source": "greeter",
           "target": "uppercaser",
           "condition": "on_success"
         }
       ]
     },
     "goal": {
       "id": "greet-user",
       "name": "Greet User",
       "description": "Generate a friendly uppercase greeting",
       "success_criteria": [{"id": "sc1", "description": "Greeting produced", "metric": "custom", "target": "any", "weight": 1.0}],
       "constraints": []
     }
   }
   ```

   **`tools.py`**:

   ```python
   def greet(name: str) -> str:
       """Generate a simple greeting."""
       return f"Hello, {name}!"

   def uppercase(greeting: str) -> str:
       """Convert text to uppercase."""
       return greeting.upper()
   ```

2. **Run the agent via CLI**

   From `core/`:

   ```bash
   python -m framework run exports/greeting-agent --input '{"name": "Alice"}'
   ```

### Actual behavior

- Execution fails when the executor tries to run the first function node (`greeter`).
- **Without fix:** `RuntimeError: Function node 'greeter' not registered. Register with node_registry.`
- **If raw callable is passed:** `'function' object has no attribute 'validate_input'` (executor expects a `NodeProtocol` implementation).

### Expected behavior

- The runner should discover function nodes from the graph, load the callables from the agent’s `tools.py` by name (`node_spec.function`), and register them with the executor’s `node_registry` (wrapped as `FunctionNode`).
- Running the same command should succeed and produce output such as:
  `"success": true`, `"output": { "final_greeting": "HELLO, ALICE!" }`.

## Root cause

- The runner loads `tools.py` only for **LLM tools** (via `ToolRegistry.discover_from_module`). It does not build a **function node registry** (node_id → implementation) for graph nodes with `node_type == "function"`.
- `GraphExecutor` is created with default `node_registry={}`, so it has no implementation for function nodes and either raises at `_get_node_implementation` or fails when treating a raw callable as a `NodeProtocol`.
- Multi-entry-point agents (`AgentRuntime` / `ExecutionStream`) also create `GraphExecutor` without a node registry, so the same failure occurs there.

## Affected code (before fix)

- **`core/framework/runner/runner.py`**
  - `_setup_legacy_executor()`: creates `GraphExecutor` without `node_registry`.
  - `_setup_agent_runtime()`: calls `create_agent_runtime()` with no function-node registry.
- **`core/framework/runtime/agent_runtime.py`**
  - `AgentRuntime` and `create_agent_runtime()` do not accept or pass a node registry.
- **`core/framework/runtime/execution_stream.py`**
  - `ExecutionStream` creates `GraphExecutor` without `node_registry`.

## Fix

See PR that implements:

1. Runner: `_build_function_node_registry()` to load `tools.py` and build node_id → `FunctionNode(callable)` for function-type nodes.
2. Runner: pass that registry into `GraphExecutor` (legacy) and into `create_agent_runtime()` (multi-entry-point).
3. AgentRuntime / create_agent_runtime / ExecutionStream: thread `node_registry` through and pass it into `GraphExecutor`.

## Status

Fixed in branch (PR linked below).
