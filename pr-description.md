# fix: multi-entry event-driven agent — transient errors, shared sessions, and TUI stability

## Summary

Fixes six interconnected bugs that prevented multi-entry-point event-driven agents (like Gmail Inbox Guardian) from working correctly. These agents have a primary user-facing entry point (e.g. rule setup) and async event-driven entry points (e.g. webhook triggers) that share a single session.

## Bugs Fixed

### 1. Transient LLM errors cause infinite retry loops (0 tokens, 50 iterations)

**Root cause:** `LiteLLMProvider.stream()` only retried `RateLimitError`. Other transient errors (`ConnectionError`, `InternalServerError`, `APIConnectionError`) were caught by the generic `except Exception` handler, which yielded a `StreamErrorEvent(recoverable=True)` without retrying. The `EventLoopNode` logged the warning and continued with an empty response — the judge saw no outputs and returned RETRY, burning all 50 iterations doing nothing.

**Fix (two layers):**

- **`litellm.py`**: Added retry with exponential backoff for transient errors in the `except Exception` handler, matching the existing `RateLimitError` retry logic.
- **`event_loop_node.py`**: After the stream completes, if a recoverable error occurred AND the response is empty (no text, no tool calls), raise `ConnectionError` so the outer transient-error handler catches it with proper backoff instead of silently burning judge iterations.

### 2. Webhook triggers create separate sessions instead of sharing the primary session

**Root cause:** `AgentRuntime._make_handler()` called `self.trigger(entry_point_id, {...})` without any `session_state`, so each webhook execution created a brand new session directory. The webhook execution couldn't access user-defined rules from the primary session, and logs were scattered across multiple session directories.

**Fix:** Added `_get_primary_session_state()` to `AgentRuntime`. When a webhook fires, it finds the active primary session, reads its `state.json`, and passes `resume_session_id` + filtered memory as `session_state`. The webhook execution now runs in the same session directory, with access to shared memory (rules, config) while stale outputs from previous runs are filtered out based on the async entry node's declared `input_keys`.

### 3. Shared-session executions overwrite the primary session's state.json

**Root cause:** `ExecutionStream._run_execution()` unconditionally called `_write_session_state()` at start, completion, error, and cancellation. When a webhook execution shared the primary session via `resume_session_id`, these writes would overwrite the primary session's state.json with the webhook execution's state.

**Fix:** Added `_is_shared_session` guard. When `session_state` contains `resume_session_id`, all `_write_session_state()` calls are skipped — the primary execution owns `state.json`, and `_write_progress()` in the executor keeps memory up-to-date at every node transition.

### 4. TUI crashes with `call_from_thread` errors on webhook events

**Root cause:** The webhook HTTP server runs on Textual's main event loop thread. When webhook events fire, `_handle_event` called `call_from_thread()` — but this method requires being called from a *different* thread. Calling it from Textual's own thread raises an exception, flooding the logs with errors for every event bus emission.

**Fix:** Check `threading.get_ident() == self._thread_id` before deciding how to route the event. If already on Textual's thread, call `_route_event()` directly. Otherwise, use `call_from_thread()` as before.

### 5. Stale memory from previous webhook runs leaks into new executions

**Root cause:** `_get_primary_session_state()` initially passed ALL memory from the primary session's `state.json`, including outputs from previous webhook runs (`emails`, `actions_taken`, `summary_report`). When `fetch-emails` received these stale outputs in memory, edge conditions and the node's own logic treated them as already-complete work.

**Fix:** Filter memory to only the keys declared in the async entry node's `input_keys` (e.g. `rules`, `max_emails`). Stale outputs from previous runs are excluded so each webhook trigger starts with clean execution state.

### 6. fetch-emails skipped on subsequent webhook triggers (stale conversation restore)

**Root cause:** Even after fixing stale memory, `fetch-emails` was still skipped. The `EventLoopNode._restore()` crash-recovery mechanism loaded the previous webhook run's conversation from `FileConversationStore`, which included a stale `OutputAccumulator` (stored in the cursor). The judge saw outputs already filled and accepted immediately without the LLM doing any work.

**Fix:** In the executor, detect fresh shared-session executions (`resume_session_id` present, no `paused_at`, no `resume_from_checkpoint`). Before the node runs, clear the stale cursor (resets the `OutputAccumulator` and iteration counter) and append a transition marker message to the conversation. The conversation history is preserved (continuous memory), but the execution state is fresh. The LLM sees the full thread plus a "NEW EVENT TRIGGER" marker and processes the new event from scratch.

## Other Changes

### AgentRunner.load() now supports multi-entry agents

- Reads `conversation_mode`, `identity_prompt`, `async_entry_points`, and `runtime_config` from agent modules
- Always creates a primary "default" entry point alongside any async entry points
- Passes `AgentRuntimeConfig` (webhook settings) through to `create_agent_runtime()`

### Graph validation supports multiple entry candidates

- `workflow.py` and `agent_builder_server.py`: Reachability check now starts from ALL entry candidates (nodes with no incoming edges), not just the first one. Fixes false "unreachable nodes" errors for agents with async entry points.

### ExecutionStream preserves graph metadata

- `_create_modified_graph()` now copies `conversation_mode`, `identity_prompt`, and `async_entry_points` from the original graph. Previously these were silently dropped, breaking continuous conversation mode and event routing for webhook-triggered executions.

## Test Plan

- [x] `test_execution_stream.py` — existing tests pass + new `test_shared_session_reuses_directory_and_memory` verifies session sharing, memory access, and state.json ownership
- [x] `test_event_loop_node.py` — existing tests pass + new `test_recoverable_stream_error_retried_not_silent` verifies recoverable stream errors raise `ConnectionError` instead of silently producing empty results
- [x] `test_executor*.py` — all executor tests pass
- [x] Gmail Inbox Guardian agent validates successfully
