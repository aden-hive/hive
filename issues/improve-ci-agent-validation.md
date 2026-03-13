# Issue: Improve CI Validation for Agent Exports

## Summary
The current CI workflow (`.github/workflows/ci.yml`) performs a trivial check on exported agents, only verifying that `agent.json` is valid JSON. It fails to validate that the file adheres to the required `GraphSpec` schema (nodes, edges, goal configuration), allowing broken agents to merge.

## Affected Code
*   **Workflow**: `.github/workflows/ci.yml` (Job: `validate`)
*   **Missing Script**: `scripts/validate_agents.py` (Need to create)

## Root Cause
The `validate` step in `ci.yml` uses a simple one-liner:
```bash
python -c "import json; json.load(open('$agent_dir/agent.json'))"
```
This accepts any valid JSON object, even `{ "foo": "bar" }`, which is not a valid agent.

## Proposed Solution

Create a dedicated validation script that enforces the Pydantic schema defined in `framework.graph`.

1.  **Create `scripts/validate_agents.py`**:
    *   Iterate through all directories in `exports/`.
    *   Load `agent.json`.
    *   Validate it using `framework.graph.GraphSpec.model_validate_json()`.
    *   Print friendly error messages if validation fails (e.g., "Missing 'nodes' field").

2.  **Update `.github/workflows/ci.yml`**:
    *   Replace the inline Python command with `python scripts/validate_agents.py`.

## Technical Details

Use the `GraphSpec` model from `core/framework/graph/edge.py` (exported in `framework.graph`):

```python
from framework.graph import GraphSpec

# ... loading logic ...
try:
    with open(agent_path, "r") as f:
        # Strict validation
        agent = GraphSpec.model_validate_json(f.read())
        print(f"✅ {agent.goal.name} is valid")
except ValidationError as e:
    print(f"❌ Invalid agent: {e}")
    sys.exit(1)
```

## Impact
*   **Reliability**: Prevents "broken" agents from being merged into `main`.
*   **Developer Experience**: strict validaton errors helps developers fix their `agent.json` faster.
