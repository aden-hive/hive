# Issue: Refactor Manual Input Validation in MCP Server

## Summary

The `agent_builder_server.py` relies on extensive manual validation logic for parsing JSON inputs and checking field existence/types. This approach is verbose, error-prone, and difficult to maintain compared to using a robust validation library like Pydantic, which is already present in the project.

## Affected Code

**File:** `core/framework/mcp/agent_builder_server.py`
**Lines:** Multiple locations, e.g., 348-365, 533-543

```python
# Lines 348-365 (set_goal)
    for i, sc in enumerate(criteria_list):
        if not isinstance(sc, dict):
            errors.append(f"success_criteria[{i}] must be an object")
        else:
            if "id" not in sc:
                errors.append(f"success_criteria[{i}] missing required field 'id'")
            # ... checks for "description", etc.
```

## Problem

1.  **High Maintenance**: Every new field requires writing manual check logic.
2.  **Inconsistency**: Different tools might handle validation slightly differently (e.g., error message formats).
3.  **Code Bloat**: significant portion of the server code is just validation plumbing.
4.  **Security**: Manual validation is more likely to miss edge cases (e.g., unexpected data types) than a mature library.

## Root Cause

The MCP tools accept JSON strings (likely due to transport constraints) and manually parse/validate them instead of leveraging Pydantic schemas for the unpacking and validation step.

## Proposed Solution

Utilize Pydantic models for input validation. Since `Goal`, `NodeSpec`, etc., are already Pydantic models (imported from `framework.graph`), the code should use `model_validate` or similar methods to parse and validate inputs.

### Refactoring Example

Instead of manual checks:
```python
    try:
        criteria_list = json.loads(success_criteria)
        # Validate list of objects
        validated_criteria = [SuccessCriterion.model_validate(sc) for sc in criteria_list]
    except ValidationError as e:
         return json.dumps({"valid": False, "errors": [str(e)]})
```

This would replace loop-based manual checking with a single line that handles types, required fields, and even complex constraints defined in the model.

## Impact

-   **Code Quality**: Reducing boilerplate makes the server code much more readable and focused on logic.
-   **Reliability**: Pydantic provides standard, tested validation logic.
