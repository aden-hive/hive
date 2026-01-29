# Summary of Changes (Session)

## 1. Contributor issue: Remove LLM dependency from Agent Builder MCP Server

- **Issue**: MCP test-generation tools had a hardcoded Anthropic dependency; contributors requested provider-agnostic behavior.
- **Resolution**: Option A was already implemented—`generate_constraint_tests` and `generate_success_tests` return guidelines/templates only; no LLM calls in the MCP server.
- **Updates**:
  - Documented resolution in `issues/remove-llm-dependency-from-mcp-server.md`.
  - Clarified `tools/mcp_server.py` docstring: no LLM/API key required at server startup; credentials validated at agent load time.
  - Added a design note in `core/framework/mcp/agent_builder_server.py` (testing tools section) to avoid reintroducing LLM dependency.

## 2. Reusable Agent Building Blocks

- **Goal**: Library of ready-to-use building blocks (retry, approval/HITL, validation) so agents can reuse patterns instead of copy-pasting.
- **Implementation**:
  - **NodeSpec** (`core/framework/graph/node.py`): Added `pause_for_hitl`, `approval_message`, `approval_timeout_seconds`.
  - **add_node / update_node** (`core/framework/mcp/agent_builder_server.py`): New optional params—`max_retries`, `retry_on`, `output_schema`, `max_validation_retries`, `pause_for_hitl`, `approval_message`. Update uses `None` = leave unchanged.
  - **Pause nodes**: Validation/export now treats a node as a pause node if `pause_for_hitl` is True or description contains `"PAUSE"` (backward compatible).
  - **Blocks library** (`core/framework/blocks/`): New package with `BlockSpec`, `get_block`, `list_blocks`. Presets: retry (default, aggressive, none, on_network), approval (required, with_message, with_timeout), validation (default, strict, none).
  - **MCP tools**: `list_blocks(category?)` and `apply_block(block_id, target_node_id, overrides?)` to list and apply presets to nodes.
  - **Docs**: `core/MCP_BUILDER_TOOLS_GUIDE.md` and `.claude/skills/building-agents-construction/SKILL.md` updated with building-blocks usage and optional node params.
  - **Tests**: `core/tests/test_blocks.py` added for the blocks registry.

## 3. safe_eval deprecation warnings (Python 3.14)

- **File**: `core/framework/graph/safe_eval.py`
- **Change**: Removed deprecated `visit_Num`, `visit_Str`, and `visit_NameConstant`; literals are handled only by `visit_Constant` (Python 3.8+ uses `ast.Constant` for all constants).
- **Result**: Deprecation warnings from pytest are gone.
