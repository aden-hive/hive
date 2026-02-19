# Phase 2: FunctionNode Removal + Dead Code Cleanup

> Ref: [GitHub Issue #4753](https://github.com/adenhq/hive/issues/4753)

## Context

`FunctionNode` (`node_type="function"`) breaks three core agent principles: conversation continuity, cumulative tools, and user interruptibility. Phase 1 (soft deprecation warnings) is complete. This plan covers Phase 2 (hard removal) plus cleanup of other dead code discovered during scoping.

**Total estimated removal: ~5,000+ lines** across production code, tests, docs, and examples.

---

## Part 1: Remove `FunctionNode` class and `"function"` node type

### 1.1 Core framework

| File | What to remove/change |
|---|---|
| `core/framework/graph/node.py` | Delete `FunctionNode` class (~L1878-1985). Remove `function` field from `NodeSpec` (~L200). |
| `core/framework/graph/executor.py` | Remove `FunctionNode` import (~L24). Remove `"function"` from `VALID_NODE_TYPES` (~L1473). Remove `node_type == "function"` branch (~L1529-1533). Remove `register_function()` (~L1975-1977). Add migration error for graphs with `node_type="function"`. |
| `core/framework/builder/workflow.py` | Remove `node_type == "function"` validation block (~L258-260). |

### 1.2 Agent Builder MCP server

| File | What to change |
|---|---|
| `core/framework/mcp/agent_builder_server.py` | Remove `"function"` from `node_type` description in `add_node` (~L590) and `update_node` (~L841). Remove `node_type == "function"` simulation branch in `test_node` (~L2356-2357). |

### 1.3 Examples & demos

| File | Action |
|---|---|
| `core/examples/manual_agent.py` | Rewrite to use `event_loop` nodes |
| `core/demos/github_outreach_demo.py` | Convert `Sender` node from `function` to `event_loop` |
| `core/examples/mcp_integration_example.py` | Rewrite to use `event_loop` nodes |

### 1.4 Docs & skills

| File | Action |
|---|---|
| `.claude/skills/hive-create/SKILL.md` | Remove `"function"` from node type table (~L495, L856) |
| `docs/developer-guide.md` | Remove `"function"` node type reference (~L613) |
| `core/MCP_SERVER_GUIDE.md` | Audit for `"function"` references |
| `docs/why-conditional-edge-priority.md` | Remove or repurpose (entire doc framed around function nodes) |
| `docs/environment-setup.md` | Remove "function" from node types list (~L216) |
| `docs/i18n/*.md` | Update BUILD diagrams in 7 i18n files (ja, ko, pt, hi, es, ru, zh-CN) removing "Function" |
| `core/framework/runtime/runtime_log_schemas.py` | Remove `"function"` from node_type comment (~L40) |

---

## Part 2: Remove deprecated `LLMNode` + `llm_tool_use` / `llm_generate`

Already soft-deprecated with `DeprecationWarning`. No template agent uses them. Only `mcp_integration_example.py` references them.

| File | What to remove/change |
|---|---|
| `core/framework/graph/node.py` | Delete `LLMNode` class (~L660-1689, ~1000 lines). Largest single removal. |
| `core/framework/graph/executor.py` | Remove `LLMNode` import. Remove `"llm_tool_use"`/`"llm_generate"` from `VALID_NODE_TYPES`. Remove `DEPRECATED_NODE_TYPES` dict. Remove their branches in `_get_node_implementation` (~L1507-1523). Update `human_input` branch to use `EventLoopNode` instead of `LLMNode`. Add migration error for deprecated types. |
| `core/framework/mcp/agent_builder_server.py` | Remove `llm_tool_use`/`llm_generate` validation warnings and branches (~L668-683, L922-937) |

---

## Part 3: Rewrite tests using `function` nodes as fixtures

These tests use `node_type="function"` as convenient scaffolding but actually test graph execution features (retries, fan-out, feedback edges, etc.). They all need rewriting.

| Test file | What it tests |
|---|---|
| `core/tests/test_on_failure_edges.py` | On-failure edge routing (~10 function nodes) |
| `core/tests/test_executor_feedback_edges.py` | Max node visits, feedback loops (~20+ function nodes) |
| `core/tests/test_executor_max_retries.py` | Retry behavior (~7 function nodes) |
| `core/tests/test_fanout.py` | Fan-out/fan-in parallel execution (~20+ function nodes) |
| `core/tests/test_execution_quality.py` | Retry + quality scoring (~8 function nodes) |
| `core/tests/test_conditional_edge_direct_key.py` | Conditional edge evaluation (~8 function nodes) |
| `core/tests/test_event_loop_integration.py` | Mixed node graph test (~2 function nodes) |
| `core/tests/test_runtime_logger.py` | Runtime log schema (~2 references) |
| `tools/tests/tools/test_runtime_logs_tool.py` | Log tool output (~2 references) |

**Strategy:** Create a `MockNode(NodeProtocol)` test helper that wraps a callable, providing the same convenience as `FunctionNode` but scoped to tests only. Tests swap `node_type="function"` for a neutral `node_type="event_loop"` and register a `MockNode` in the executor's `node_registry`. This minimizes rewrite effort.

---

## Part 4: Items NOT recommended for removal

| Item | Reason to keep |
|---|---|
| `RouterNode` | Architecturally sound (deterministic routing), just lacks template examples |
| `human_input` node type | Valid HITL pattern, but switch implementation from `LLMNode` to `EventLoopNode` |
| `register_function` in `tool_registry.py` | For **tool** registration — completely different concept from function nodes |

---

## Part 5: Remove the Planner-Worker subsystem (~3,900 lines dead code)

The entire Planner-Worker-Judge pattern has **zero external consumers**. No template agent, example, demo, or runner references it. It is only consumed by:
- Its own internal files (self-referential imports)
- The agent-builder MCP server (exposes tools for it)
- Its own dedicated tests

### 5.1 Delete these files entirely

| File | Lines | What |
|---|---|---|
| `core/framework/graph/flexible_executor.py` | 552 | `FlexibleGraphExecutor` — Worker-Judge orchestrator |
| `core/framework/graph/worker_node.py` | 620 | `WorkerNode` — plan step dispatcher |
| `core/framework/graph/plan.py` | 513 | `Plan`, `PlanStep`, `ActionType`, `ActionSpec` data structures |
| `core/framework/graph/judge.py` | 406 | `HybridJudge` — step result evaluator |
| `core/framework/graph/code_sandbox.py` | 413 | `CodeSandbox` — sandboxed code execution |
| `core/tests/test_flexible_executor.py` | 442 | FlexibleGraphExecutor tests |
| `core/tests/test_plan.py` | 592 | Plan data structure tests |
| `core/tests/test_plan_dependency_resolution.py` | 384 | Plan dependency resolution tests |

### 5.2 Clean up exports

`core/framework/graph/__init__.py` — Remove all planner-worker exports: `FlexibleGraphExecutor`, `ExecutorConfig`, `WorkerNode`, `StepExecutionResult`, `HybridJudge`, `create_default_judge`, `CodeSandbox`, `safe_eval`, `safe_exec`, `Plan`, `PlanStep`, `ActionType`, `ActionSpec`, and all related symbols.

### 5.3 Remove MCP tools from agent-builder server

`core/framework/mcp/agent_builder_server.py` — Remove these 7 MCP tools:

| MCP tool | Description |
|---|---|
| `create_plan` | Creates a plan with steps |
| `validate_plan` | Validates plan structure |
| `simulate_plan_execution` | Dry-run simulation |
| `load_exported_plan` | Loads plan from JSON |
| `add_evaluation_rule` | Adds HybridJudge rule |
| `list_evaluation_rules` | Lists evaluation rules |
| `remove_evaluation_rule` | Removes evaluation rule |

Also remove:
- `from framework.graph.plan import Plan` import (~L39, L3731)
- `_evaluation_rules` global list (~L2528)
- `"evaluation_rules"` from export/session data (~L1859)
- `load_plan_from_json()` helper function (~L3721-3733)

---

## Execution order

1. **Create `MockNode` test helper** — unblocks all test rewrites
2. **Rewrite tests** using function nodes as fixtures (Part 3)
3. **Remove `FunctionNode` class + all references** (Part 1)
4. **Remove `LLMNode` class + deprecated types** (Part 2)
5. **Delete Planner-Worker subsystem files** (Part 5.1)
6. **Clean up `__init__.py` exports** (Part 5.2)
7. **Remove MCP tools** for plans/evaluation from agent-builder server (Part 5.3)
8. **Update examples/demos/docs/skills** (Parts 1.3, 1.4)
9. **Run full test suite** to verify

---

## Verification

1. `pytest core/tests/` — all tests pass
2. `pytest tools/tests/` — runtime log tests pass
3. Load any template agent JSON — no errors
4. Attempt to load a graph with `node_type="function"` — clear `RuntimeError` with migration guidance
5. Attempt to load a graph with `node_type="llm_tool_use"` — clear `RuntimeError` with migration guidance
6. Agent builder MCP: `add_node` with `node_type="function"` — rejected with helpful message
7. Plan/evaluation MCP tools no longer appear in tool list
