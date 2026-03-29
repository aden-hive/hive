# Framework

A goal-driven agent runtime with Builder-friendly observability.

## Overview

Framework provides a runtime framework that captures **decisions**, not just actions. This enables a "Builder" LLM to analyze and improve agent behavior by understanding:

- What the agent was trying to accomplish
- What options it considered
- What it chose and why
- What happened as a result

## Installation

```bash
uv pip install -e .
```

## Agent Building

Agent scaffolding is handled by the `coder-tools` MCP server (in `tools/coder_tools_server.py`), which provides the `initialize_and_build_agent` tool and related utilities. The package generation logic lives directly in `tools/coder_tools_server.py`.

See the [Getting Started Guide](../docs/getting-started.md) for building agents.

## Quick Start

### Calculator Agent

Run an LLM-powered calculator:

```bash
# Run an exported agent
uv run python -m framework run exports/calculator --input '{"expression": "2 + 3 * 4"}'

# Interactive shell session
uv run python -m framework shell exports/calculator

# Show agent info
uv run python -m framework info exports/calculator
```

### Using the Runtime

```python
from framework import Runtime

runtime = Runtime("/path/to/storage")

# Start a run
run_id = runtime.start_run("my_goal", "Description of what we're doing")

# Record a decision
decision_id = runtime.decide(
    intent="Choose how to process the data",
    options=[
        {"id": "fast", "description": "Quick processing", "pros": ["Fast"], "cons": ["Less accurate"]},
        {"id": "thorough", "description": "Detailed processing", "pros": ["Accurate"], "cons": ["Slower"]},
    ],
    chosen="thorough",
    reasoning="Accuracy is more important for this task"
)

# Record the outcome
runtime.record_outcome(
    decision_id=decision_id,
    success=True,
    result={"processed": 100},
    summary="Processed 100 items with detailed analysis"
)

# End the run
runtime.end_run(success=True, narrative="Successfully processed all data")
```

### Testing Agents

The framework includes a goal-based testing framework for validating agent behavior.

Tests are generated using MCP tools (`generate_constraint_tests`, `generate_success_tests`) which return guidelines. Claude writes tests directly using the Write tool based on these guidelines.

```bash
# Run tests against an agent
uv run python -m framework test-run <agent_path> --goal <goal_id> --parallel 4

# Debug failed tests
uv run python -m framework test-debug <agent_path> <test_name>

# List tests for an agent
uv run python -m framework test-list <agent_path>
```

For detailed testing workflows, see [developer-guide.md](../docs/developer-guide.md).

### Analyzing Agent Behavior with Builder

The BuilderQuery interface allows you to analyze agent runs and identify improvements:

```python
from framework import BuilderQuery

query = BuilderQuery("/path/to/storage")

# Find patterns across runs
patterns = query.find_patterns("my_goal")
print(f"Success rate: {patterns.success_rate:.1%}")

# Analyze a failure
analysis = query.analyze_failure("run_123")
print(f"Root cause: {analysis.root_cause}")
print(f"Suggestions: {analysis.suggestions}")

# Get improvement recommendations
suggestions = query.suggest_improvements("my_goal")
for s in suggestions:
    print(f"[{s['priority']}] {s['recommendation']}")
```

## Architecture

```
┌─────────────────┐
│  Human Engineer │  ← Supervision, approval
└────────┬────────┘
         │
┌────────▼────────┐
│   Builder LLM   │  ← Analyzes runs, suggests improvements
│  (BuilderQuery) │
└────────┬────────┘
         │
┌────────▼────────┐
│   Agent LLM     │  ← Executes tasks, records decisions
│    (Runtime)    │
└─────────────────┘
```

## Key Concepts

- **Decision**: The atomic unit of agent behavior. Captures intent, options, choice, and reasoning.
- **Run**: A complete execution with all decisions and outcomes.
- **Runtime**: Interface agents use to record their behavior.
- **BuilderQuery**: Interface Builder uses to analyze agent behavior.

## Requirements

- Python 3.11+
- pydantic >= 2.0
- anthropic >= 0.40.0 (for LLM-powered agents)
