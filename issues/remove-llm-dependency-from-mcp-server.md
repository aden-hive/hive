# Issue: Remove LLM Dependency from Agent Builder MCP Server

## Summary

The `agent_builder_server.py` MCP server has a hardcoded dependency on `AnthropicProvider` for test generation, which:
1. Breaks when users don't have an Anthropic API key
2. Is redundant since the calling agent (Claude) can write tests directly
3. Violates the principle that MCP servers should be provider-agnostic utilities

## Affected Code

**File:** `core/framework/mcp/agent_builder_server.py`

**Lines:** 2350-2351, 2413-2414

```python
# Line 2350-2351 (generate_constraint_tests)
from framework.llm import AnthropicProvider
llm = AnthropicProvider()

# Line 2413-2414 (generate_success_tests)
from framework.llm import AnthropicProvider
llm = AnthropicProvider()
```

**Introduced by:** bryan (commit e2945b6c, 2026-01-20)

## Problem

When a user configures their agent to use a non-Anthropic LLM provider (e.g., `LiteLLMProvider` with Cerebras, OpenAI, or other backends), the MCP test generation tools fail with:

```
{"error": "Failed to initialize LLM: Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."}
```

This happens even though:
- The user has valid credentials for their chosen provider
- The calling Claude agent is fully capable of writing tests
- MCP is an open standard that shouldn't mandate specific LLM providers

## Root Cause

The test generation functions (`generate_constraint_tests`, `generate_success_tests`) embed an LLM call to generate Python test code from goal definitions. This design:

1. **Duplicates capability** - The outer Claude agent already writes code; delegating to an inner LLM is redundant
2. **Creates provider lock-in** - Hardcoding `AnthropicProvider` breaks multi-provider workflows
3. **Adds complexity** - Requires managing credentials in two places (outer agent + MCP server)

## Proposed Solution

**Option A: Remove LLM dependency entirely (Recommended)**

Refactor the MCP server to only provide test execution utilities:
- `run_tests` - Execute pytest and return structured results
- `list_tests` - Scan test files in agent directory
- `debug_test` - Re-run single test with verbose output

Test *generation* becomes the responsibility of the calling agent, which:
- Already has LLM capability
- Already knows the goal/constraints
- Can write tests directly using `Write` tool

**Option B: Make LLM provider configurable**

If LLM-based generation must stay in the MCP server:
```python
# Accept model parameter, use LiteLLM for provider-agnostic support
from framework.llm.litellm import LiteLLMProvider

def generate_constraint_tests(goal_id, goal_json, agent_path, model="gpt-4o-mini"):
    llm = LiteLLMProvider(model=model)
    # ...
```

## Impact

- Users with non-Anthropic setups cannot use `generate_constraint_tests` or `generate_success_tests`
- Workaround: Write tests manually (as done in this session)
- Skills documentation (`testing-agent`) mandates MCP tools but they don't work universally

## Recommendation

Implement **Option A**. The MCP server should be a thin utility layer for test execution, not a code generator. This:
- Eliminates provider dependency
- Simplifies the codebase
- Aligns with MCP's role as a protocol, not an LLM wrapper

## Related Files

- `core/framework/mcp/agent_builder_server.py` - Main file to modify
- `.claude/skills/testing-agent/SKILL.md` - Update documentation if tools change
- `core/framework/testing/` - Test generation utilities that could be removed
