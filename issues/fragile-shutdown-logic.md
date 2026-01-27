# Issue: Fragile Shutdown Logic causing Potential Hangs

## Summary

The `AgentRuntime` and `ExecutionStream` shutdown sequences (`stop()` methods) iterate through running tasks and await their cancellation **sequentially**. If a single task fails to handle cancellation correctly (e.g., catches `CancelledError` without re-raising or enters a tight loop), the entire shutdown process hangs indefinitely.

## Affected Code

**File:** `core/framework/runtime/agent_runtime.py`
**File:** `core/framework/runtime/execution_stream.py`

## Problem

1.  **Sequential Waits:**
    *   `AgentRuntime.stop`: `for stream in self._streams.values(): await stream.stop()` (line 224)
    *   `ExecutionStream.stop`: `for exec_id, task in self._execution_tasks.items(): ... await task` (lines 182-186)
2.  **Blocking Risk:** If the first item in the list hangs, the subsequent items are never cancelled or stopped.
3.  **Inefficiency:** Shutdown time is the *sum* of all timeouts rather than the *max* of concurrent timeouts.

## Root Cause

Naive iteration over async resources instead of using concurrent primitives like `asyncio.gather` with timeouts.

## Proposed Solution

1.  **Concurrent Shutdown:** Use `asyncio.gather(*[stream.stop() for stream in streams])` to stop all streams in parallel.
2.  **Timeouts:** Apply `asyncio.wait_for` with a timeout to the shutdown logic to force-kill stubborn tasks after a grace period.
3.  **Loop Safety:** Ensure `ExecutionStream` cancels *all* tasks before awaiting *any* of them.

## Impact

-   **Severity:** Medium/High.
-   **Consequence:** Application fails to restart or exit cleanly (Zombie processes), requiring `kill -9`.

## Recommendation

Refactor `stop()` methods to use `asyncio.gather` and impose a global shutdown timeout.
