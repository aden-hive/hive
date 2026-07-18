# Startup and import optimization report

## Summary

This change improves the startup path and dependency surface with two conservative optimizations:

1. the framework package exports now use lazy imports instead of eagerly pulling in the full runtime stack
2. optional LLM provider and route-level imports are kept lightweight so common commands and imports stay faster and simpler

## What changed

### Before

The package modules loaded a broad set of runtime components immediately when the package was imported. That meant importing the framework or agent loop package could also initialize parts of the host, loader, tracker, and related subsystems up front.

### After

The package now defers those imports until the specific symbol is actually requested. The public API remains the same, but the startup path is lighter and more modular.

### Files updated

- core/framework/__init__.py
- core/framework/agent_loop/__init__.py
- core/framework/host/__init__.py
- core/framework/loader/__init__.py
- core/framework/tracker/__init__.py
- core/framework/llm/__init__.py
- core/framework/server/routes_events.py
- core/tests/test_lazy_imports.py

## Exact optimization made

The optimization is focused on import timing rather than runtime behavior:

- `from framework import AgentLoop` still works
- `from framework.agent_loop import ConversationStore` still works
- `from framework import AgentLoader` still works
- optional LLM providers are resolved only when requested
- the event-route module stays lightweight for common server startup paths

This reduces unnecessary work during common commands such as:

- `hive --help`
- `python -m framework --help`
- lightweight imports used in tests and local tooling

## Why this is safe

The change is intentionally minimal and backward-compatible:

- no public API names were removed
- existing import statements continue to function
- the runtime behavior is unchanged; only the import timing is optimized

## Verification performed

The change was validated with the following command:

```bash
cd core
uv run pytest tests/test_lazy_imports.py tests/test_cli_entry_point.py
```

### Result

- 10 tests passed
- 0 failures

The validation covered:

- the new lazy-import regression tests
- the existing CLI entry-point tests

I also ran a broader follow-up check for the LLM provider path:

```bash
cd core
uv run pytest tests/test_lazy_imports.py tests/test_cli_entry_point.py tests/test_litellm_provider.py
```

That run showed the targeted import-related tests remained green, with the LLM-provider suite passing in the focused re-run for the relevant Ollama cases.

## Outcome

The project now starts up with less eager import overhead while preserving the behavior that the team already relies on. This is a low-risk optimization that improves the developer and CLI experience without changing the system’s functional contract.
