# Testing Guide

This guide covers how to test Hive agents with or without Claude Code. All testing features work without a Claude Code subscription.

## Quick Reference

| Method              | Command                                                       | Use Case                          |
| ------------------- | ------------------------------------------------------------- | --------------------------------- |
| Claude Code         | `claude> /hive-test`                                         | Interactive test loop with Claude |
| Test suite          | `PYTHONPATH=exports uv run python -m my_agent test`           | Run all pytest tests              |
| Mock run            | `PYTHONPATH=exports uv run python -m my_agent run --mock ...` | Validate structure, no API calls  |
| Hive CLI            | `hive run exports/my_agent --input '{}'`                      | Run agent with real LLM           |

Replace `my_agent` with your agent's package name.

## Manual Testing (No Claude Code)

### Run the Test Suite

Agents created with `/hive-create` or from templates include a `tests/` directory. Run them with:

```bash
# Run all tests
PYTHONPATH=exports uv run python -m my_agent test

# Test specific criteria
PYTHONPATH=exports uv run python -m my_agent test --type success
PYTHONPATH=exports uv run python -m my_agent test --type constraint

# Parallel execution (faster)
PYTHONPATH=exports uv run python -m my_agent test --parallel 4

# Stop on first failure
PYTHONPATH=exports uv run python -m my_agent test --fail-fast
```

### Mock Mode

Mock mode runs the agent without calling real LLM APIs. Use it to:

- Validate graph structure (nodes, edges, connections)
- Verify the agent loads and is importable
- Test locally without API keys or credits

```bash
PYTHONPATH=exports uv run python -m my_agent run --mock --input '{"task": "example"}'
```

**Limitation:** Mock mode only validates structure. It does not test LLM reasoning, content quality, or real API integrations. For goal-achievement testing, use real credentials.

### Run with Real LLM

```bash
# Via hive CLI
hive run exports/my_agent --input '{"task": "your input"}'

# Via agent module (if agent has run command)
PYTHONPATH=exports uv run python -m my_agent run --input '{"task": "your input"}'
```

Ensure `ANTHROPIC_API_KEY` (or your LLM provider key) is set.

## Writing Custom Tests

### Test File Structure

```
exports/my_agent/
├── agent.py
├── nodes/
└── tests/
    ├── conftest.py           # Shared fixtures
    ├── test_constraints.py    # Constraint tests
    └── test_success_criteria.py
```

### Key Patterns

- Every test must be `async` with `@pytest.mark.asyncio`
- Use `runner` and `auto_responder` fixtures (provided by framework)
- Use `await runner.run(input_dict)` — not `default_agent.run()`
- Access output via `result.output.get("key")` — never `result.output["key"]`
- `result.success=True` means no exception, not goal achieved — always check output

See [developer-guide.md](developer-guide.md#testing-agents) for a basic example and [.claude/skills/hive-test/SKILL.md](../.claude/skills/hive-test/SKILL.md) for the full iterative testing workflow, safe patterns, and credential requirements.

## Framework Test Commands

For advanced workflows (test generation, debugging, checkpoint resume):

```bash
# List tests for an agent
uv run python -m framework test-list exports/my_agent --goal <goal_id>

# Run tests for a specific goal
uv run python -m framework test-run exports/my_agent --goal <goal_id>

# Debug a failing test
uv run python -m framework test-debug exports/my_agent <test_name>
```

See [core/README.md](../core/README.md) for details.

## Credentials

Testing with real LLMs requires:

1. **LLM API key** — e.g. `ANTHROPIC_API_KEY`
2. **Tool credentials** — if the agent uses tools (HubSpot, Brave Search, etc.)

Use `/hive-credentials` in Claude Code or configure credentials manually. See [hive-test skill](../.claude/skills/hive-test/SKILL.md#credential-requirements) for the full credential checklist.
