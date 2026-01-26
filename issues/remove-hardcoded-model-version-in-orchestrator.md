# Issue: Remove Hardcoded Model Version in AgentOrchestrator

## Summary

The `AgentOrchestrator` class initializes with a hardcoded, specific model version string (`claude-haiku-4-5-20251001`) as the default. This is likely a placeholder or internal identifier that will fail for public users, causing the orchestrator to break if no model is explicitly provided.

## Affected Code

**File:** `core/framework/runner/orchestrator.py`
**Lines:** 58-59

```python
    def __init__(
        self,
        llm: LLMProvider | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
```

## Problem

1.  **Invalid Model Name**: `claude-haiku-4-5-20251001` does not appear to be a standard public model name (standard is `claude-3-haiku-20240307` or similar).
2.  **API Failure**: Calls to `LiteLLMProvider(model=self._model)` will likely fail with a `BadRequestError` or `NotFoundError` from the provider if the model name is invalid.
3.  **Fragility**: Hardcoding a date-stamped version makes the code brittle and requiring updates whenever models change.

## Root Cause

The default parameter likely references a development or internal preview version of a model that was used during testing/creation and was committed to the codebase.

## Proposed Solution

Change the default model to a widely available, stable model alias, or allow it to be configured via environment variables.

### Recommended Change

```python
# Use a stable alias or environment variable
import os

DEFAULT_ROUTING_MODEL = os.getenv("HIVE_ROUTING_MODEL", "claude-3-haiku-20240307")

class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMProvider | None = None,
        model: str = DEFAULT_ROUTING_MODEL,
    ):
        # ...
```

## Impact

-   **Runtime Errors**: Users trying to use `AgentOrchestrator` without specifying a model will experience immediate crashes during initialization or first routing call.
-   **Adoption Barrier**: New users following examples (which might imply default usage) will encounter errors.
