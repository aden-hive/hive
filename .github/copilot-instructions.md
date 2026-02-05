# Aden Agent Framework - Copilot Instructions

## Architecture Overview

Goal-driven AI agent framework where agents record **decisions** (intent → options → choice → outcome), enabling a "Builder" LLM to analyze and improve behavior.

### Package Structure
- **`core/framework/`** - Runtime, graph executor, LLM providers (installed as `framework`)
- **`tools/`** - MCP tools for file ops, web search (installed as `aden_tools`)
- **`exports/`** - Agent packages ready to run

### Data Flow
```
Goal + GraphSpec → GraphExecutor.execute() → NodeSpec.execute() → NodeResult
                        ↓                            ↓
                   Runtime.decide()           Runtime.record_outcome()
```

## Commands

```bash
# Setup (run once)
./scripts/setup-python.sh && ./quickstart.sh

# Daily workflow
make lint        # Ruff auto-fix
make test        # pytest core/tests/

# Run agents
PYTHONPATH=core:exports python -m content_marketing_agent validate  # Check graph
PYTHONPATH=core:exports python -m content_marketing_agent run --mock  # Dry run
```

**Mock mode** (`--mock`): Graph traversal without LLM calls. **Live mode**: Needs `ANTHROPIC_API_KEY`.

## Python Conventions

**Style** (Ruff enforced, config in `core/pyproject.toml`):
- Line length: 100, Python 3.11+
- Always: `from __future__ import annotations`
- Imports: stdlib → third-party → `framework` → local
- Pydantic `BaseModel` for all schemas

```python
from __future__ import annotations
from pydantic import BaseModel
from framework.graph import GraphSpec, Goal, EdgeSpec, EdgeCondition
from .config import load_config
```

## Core Concepts

### Goals (`framework.graph.goal`)
Goals are declarative—define WHAT, not HOW. See `exports/content_marketing_agent/agent.py`:
```python
Goal(id="...", name="...", description="...",
     success_criteria=[SuccessCriterion(metric="output_contains", target="...")],
     constraints=[Constraint(constraint_type="hard", category="safety")])
```

### Nodes & Edges (`framework.graph.node`, `framework.graph.edge`)
**Node types**: `llm_generate`, `llm_tool_use`, `function`, `router`, `human_input`
**Edge conditions**: `ALWAYS`, `ON_SUCCESS`, `ON_FAILURE`, `CONDITIONAL`, `LLM_DECIDE`

```python
EdgeSpec(source="validator", target="retry", condition=EdgeCondition.CONDITIONAL,
         condition_expr="output.confidence < 0.8")  # Safe eval only
```

### Runtime Decision Recording (`framework.runtime.core`)
```python
decision_id = runtime.decide(intent="...", options=[...], chosen="...", reasoning="...")
runtime.record_outcome(decision_id, success=True, result={...})
```

## Testing

Tests in `core/tests/`. Always use `DummyRuntime` and `@pytest.mark.asyncio`:
```python
class DummyRuntime:
    def start_run(self, **kwargs): return "run-1"
    def end_run(self, **kwargs): pass
    def report_problem(self, **kwargs): pass

@pytest.mark.asyncio
async def test_executor():
    result = await GraphExecutor(runtime=DummyRuntime(), node_registry={...}).execute(graph, goal)
    assert result.success
```

## Agent Package Structure (`exports/`)

Reference: `exports/content_marketing_agent/`
```
agent_name/
├── __main__.py    # CLI: info, run, validate (uses click)
├── agent.py       # Goal, GraphSpec, edges
├── nodes.py       # NodeSpec definitions
├── tools.py       # Tool objects for LLM
└── config.py      # Pydantic config
```

## Key Files

| Purpose | File |
|---------|------|
| GraphSpec, EdgeSpec | `core/framework/graph/edge.py` |
| NodeSpec, NodeResult | `core/framework/graph/node.py` |
| Goal, SuccessCriterion | `core/framework/graph/goal.py` |
| GraphExecutor | `core/framework/graph/executor.py` |
| Runtime.decide() | `core/framework/runtime/core.py` |
| LLMProvider, Tool | `core/framework/llm/provider.py` |
| MCP tools | `tools/README.md` |
| Example agent | `exports/content_marketing_agent/` |
