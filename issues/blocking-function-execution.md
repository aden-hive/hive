# Issue: FunctionNode Blocks Event Loop

## Summary

The `FunctionNode` class executes user-provided functions synchronously on the main thread. If a user function performs long-running computations or blocking I/O (e.g., `requests.get`, `time.sleep`), it freezes the entire `AgentRuntime`, blocking all other concurrent agents and entry points.

## Affected Code

**File:** `core/framework/graph/node.py`

## Problem

1.  **Sync Execution:** `FunctionNode.execute` calls `self.func(**ctx.input_data)` directly (line 1067) without `await` or offloading.
2.  **Single Threaded:** In Python's `asyncio`, the event loop is single-threaded. Any blocking call stops the heart of the framework.
3.  **No Async Support:** The code does not check if `self.func` is a coroutine. If a user passes an `async def` function, `FunctionNode` will return the coroutine object as the result instead of awaiting it.

## Root Cause

`FunctionNode` assumes functions are "deterministic operations that don't need LLM reasoning" (docstring), implicitly treating them as instant CPU operations, which is rarely true in integration contexts.

## Proposed Solution

1.  **Support Async:** Inspect if `self.func` is a coroutine function (using `inspect.iscoroutinefunction`) and `await` it if so.
2.  **Offload Sync:** If `self.func` is synchronous, run it in a thread pool using `loop.run_in_executor` to prevent blocking the main loop.

## Impact

-   **Severity:** High.
-   **Consequence:** Degraded performance and potential system freeze. A single slow function impacting one user affects all users sharing the runtime.

## Recommendation

Refactor `FunctionNode.execute` to handle both `async` functions (await them) and sync functions (offload to thread pool).
