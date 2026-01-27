# Issue: Unbounded Memory Growth in ExecutionStream

## Summary

The `ExecutionStream` class retains the context of *every* execution it processes in memory indefinitely, leading to a memory leak that will eventually crash long-running agents (e.g., webhook listeners) with an Out Of Memory (OOM) error.

## Affected Code

**File:** `core/framework/runtime/execution_stream.py`

## Problem

1.  **Retention:** `ExecutionContext` objects are stored in `self._active_executions` (line 242) keyed by execution ID.
2.  **No Cleanup:** While `self._state_manager.cleanup_execution(execution_id)` (line 353) is called to clean up shared state, the *local* `ExecutionContext` object is **never removed** from `self._active_executions` in the `_run_execution` method or `wait_for_completion`.
3.  **Growth:** For event-driven agents (e.g., handling 10k webhooks/day), this dictionary grows monotonically until the process dies.

## Root Cause

Misunderstanding of lifecycle management combined with properties like `get_stats()` (line 453) which iterate over the entire history. The code treats `_active_executions` as a history log rather than a set of currently running tasks.

## Proposed Solution

1.  **Remove upon Completion:** Remove the `ctx` from `_active_executions` in the `finally` block of `_run_execution`.
2.  **Separate History:** If history is needed, move completed executions to a ring buffer (limited size list) or rely on `EventBus` for archival.

## Impact

-   **Severity:** Critical for long-running agents.
-   **Consequence:** Process crash (OOM) after sufficient runtime/load.

## Recommendation

Modify `_run_execution` to `del self._active_executions[execution_id]` after completion.
