# PR body (copy when opening the PR)

## Description

Fixes runtime failure when running exported agents that use **function** nodes. The runner now builds a function-node registry from the agent's `tools.py` and passes it to the executor (legacy and multi-entry-point), so function-type nodes execute instead of raising "Function node 'X' not registered".

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Related Issues

Fixes #3107

## Changes Made

- **runner.py**: Add `_build_function_node_registry()` to load agent's `tools.py` and build `node_id -> FunctionNode(callable)` for graph nodes with `node_type == "function"`. Pass that registry into `GraphExecutor` (legacy) and into `create_agent_runtime()` (multi-entry-point).
- **agent_runtime.py**: Add optional `node_registry` to `AgentRuntime.__init__` and `create_agent_runtime()`; pass it to `ExecutionStream`.
- **execution_stream.py**: Add optional `node_registry` to `ExecutionStream.__init__`; pass it to `GraphExecutor` when creating the executor per execution.

## Testing

- [x] Unit tests pass: `cd core && pytest tests/ framework/runtime/tests/` (229 passed)
- [x] Manual: Created `exports/greeting-agent` (agent.json + tools.py with greet/uppercase), ran `python -m framework run exports/greeting-agent --input '{"name": "Alice"}' --quiet` → success, output `"final_greeting": "HELLO, ALICE!"`

## Checklist

- [x] My code follows the project's style guidelines
- [x] I have performed a self-review of my code
- [x] New and existing unit tests pass locally with my changes
