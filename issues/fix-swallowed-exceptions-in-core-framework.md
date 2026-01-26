# Issue: Fix Swallowed Exceptions in Core Framework

## Summary

Multiple core components, including `AgentOrchestrator` and `AgentBuilderServer`, catch broad `Exception` without logging or re-raising. This "swallowing" of exceptions hides errors, making debugging difficult and potentially masking critical failures like configuration issues or interrupted system calls.

## Affected Code

**File:** `core/framework/mcp/agent_builder_server.py`
**Lines:** 158-159, 215-216

```python
# Line 158-159 (_load_active_session)
    except Exception:
        pass

# Line 215-216 (list_sessions)
            except Exception:
                pass  # Skip corrupted files
```

**File:** `core/framework/runner/orchestrator.py`
**Lines:** 479-480

```python
# Line 479-480 (_llm_route)
        except Exception:
            pass
```

## Problem

The codebase frequently uses the pattern:
```python
try:
    # operation
except Exception:
    pass
```

This is problematic because:
1.  **Hides Bugs**: Logic errors (e.g., `NameError`, `AttributeError`) are silently ignored.
2.  **Masks Configuration Issues**: Permission errors or missing files are treated as "not found" or "no result" without informing the user.
3.  **Harder Debugging**: Developers cannot see why an operation failed (e.g., why a session didn't load or why LLM routing failed).

## Root Cause

The code attempts to be robust by preventing crashes on minor errors, but does so excessively by silencing *all* errors. This implies a defensive programming style that prioritizes uptime over correctness/visibility, but applies it too broadly.

## Proposed Solution

1.  **Log the error**: Use the `logging` module to log the exception before passing (or returning fallback).
2.  **Narrow the exception type**: Catch specific exceptions (e.g., `FileNotFoundError`, `json.JSONDecodeError`) instead of `Exception`.
3.  **Re-raise or Return Error State**: If the error is unexpected, let it bubble up or return a structured error result.

### Example Fix for `_load_active_session`

```python
import logging
logger = logging.getLogger(__name__)

def _load_active_session() -> BuildSession | None:
    if not ACTIVE_SESSION_FILE.exists():
        return None

    try:
        with open(ACTIVE_SESSION_FILE, "r") as f:
            session_id = f.read().strip()
        if session_id:
            return _load_session(session_id)
    except (FileNotFoundError, ValueError):
        # Expected errors if file removed or content invalid
        return None
    except Exception as e:
        # Unexpected errors should be logged
        logger.error(f"Failed to load active session: {e}", exc_info=True)
        return None
```

## Impact

-   **Low Visibility**: Users/Devs won't know if the system is failing silently.
-   **Stability Risk**: Critical errors might be ignored, leading to inconsistent state (e.g., corrupted session files ignored completely instead of alerting).
