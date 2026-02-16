## Summary

- Add `acomplete()` and `acomplete_with_tools()` async methods to the `LLMProvider` base class, with a safe `run_in_executor` default that prevents any provider from blocking the event loop
- Implement native async I/O in `LiteLLMProvider` using `litellm.acompletion()` and `asyncio.sleep()` for retries, eliminating thread-pool overhead
- Migrate 15 call sites across the framework (nodes, judges, edges, executor, runner, orchestrator) from sync `complete()` to async `acomplete()`
- Propagate async through internal call chains: `edge.should_traverse()`, `output_cleaner.clean_output()`, `executor._follow_edges()`, `executor._get_all_traversable_edges()`

Fixes #4905

## Context

Every non-streaming LLM call in the framework used the synchronous `complete()` / `complete_with_tools()` methods directly from async code. Because Python's asyncio event loop is single-threaded, these blocking calls froze the entire loop for the duration of each API round-trip (often 5-30+ seconds). This prevented concurrent coroutines from making progress — heartbeats stalled, parallel node execution serialized, and the TUI became unresponsive during LLM calls.

The streaming path (`stream()`) already used `litellm.acompletion()` and was unaffected. Only the non-streaming paths were blocking.

## Changes

### LLM Provider Interface (`provider.py`)

- Added `acomplete()` with a `run_in_executor` default — any `LLMProvider` subclass automatically gets a non-blocking async path, even without overriding
- Added `acomplete_with_tools()` with the same safety-net pattern
- Updated `stream()` default implementation to call `acomplete()` instead of sync `complete()`

### LiteLLMProvider (`litellm.py`)

- Added `_acompletion_with_rate_limit_retry()` — async mirror of the sync retry logic, using `litellm.acompletion()` for non-blocking HTTP and `asyncio.sleep()` for non-blocking backoff
- Added native `acomplete()` override — bypasses `run_in_executor`, uses true async I/O
- Added native `acomplete_with_tools()` override — async tool-use loop

### AnthropicProvider (`anthropic.py`)

- Added `acomplete()` and `acomplete_with_tools()` delegates to `self._provider.acomplete()`

### MockLLMProvider (`mock.py`)

- Added `acomplete()` and `acomplete_with_tools()` — call through to sync (no I/O, instant return)

### Framework Call Sites (13 direct + 4 indirect)

| File | Method | Change |
|------|--------|--------|
| `event_loop_node.py` | compaction summary | `complete()` → `await acomplete()` |
| `node.py` | LLMNode execute (7 sites) | `complete()` / `complete_with_tools()` → async |
| `judge.py` | HybridJudge evaluate | `complete()` → `await acomplete()` |
| `conversation_judge.py` | Level 2 judge | `complete()` → `await acomplete()` |
| `worker_node.py` | WorkerNode execute | `complete()` → `await acomplete()` |
| `edge.py` | `should_traverse()`, `_llm_decide()` | Made async, `complete()` → `await acomplete()` |
| `output_cleaner.py` | `clean_output()` | Made async, `complete()` → `await acomplete()` |
| `executor.py` | `_follow_edges()`, `_get_all_traversable_edges()` | Made async, propagated `await` to all callers |
| `runner.py` | capability check | `complete()` → `await acomplete()` |
| `orchestrator.py` | multi-agent routing | `complete()` → `await acomplete()` |

### Intentionally Left As-Is

- `node.py:_extract_json()` — rare last-resort fallback that creates its own provider instance; not on the hot path
- `context_handoff.py:_llm_summary()` — not called from the executor's async context
- `testing/llm_judge.py` — test-only utility

### Tests

- 5 new async tests in `test_litellm_provider.py`:
  - `test_acomplete_uses_acompletion` — verifies `litellm.acompletion` is called
  - `test_acomplete_does_not_block_event_loop` — heartbeat task runs concurrently during a simulated 300ms LLM call
  - `test_acomplete_with_tools_uses_acompletion` — verifies async tool-use path
  - `test_mock_provider_acomplete` — MockLLMProvider async works
  - `test_base_provider_acomplete_offloads_to_executor` — verifies `run_in_executor` runs on a different thread
- Fixed 3 test providers (`test_execution_stream.py`, `test_llm_judge.py`, `test_event_loop_integration.py`) that were missing the `max_retries` parameter
- All 765 existing tests pass

## Test plan

- [x] All 765 existing tests pass (no regressions)
- [x] 5 new async tests pass, including event-loop-blocking proof test
- [ ] Manual smoke test: run an agent with `hive run` and verify TUI remains responsive during LLM calls
- [ ] Manual smoke test: run parallel node execution and verify nodes execute concurrently, not serially
