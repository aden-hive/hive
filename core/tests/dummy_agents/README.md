# Dummy Agent Tests (Level 2)

End-to-end tests that run real LLM calls against deterministic graph structures. Not part of CI — run manually to verify the executor works with real providers.

## Quick Start

```bash
cd core
uv run python tests/dummy_agents/run_all.py
```

The script detects available credentials and prompts you to pick a provider. You need at least one of:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `KIMI_API_KEY`
- `ZAI_API_KEY`
- Claude Code / Codex / Kimi subscription

## Verbose Mode

Show live LLM logs (tool calls, judge verdicts, node traversal):

```bash
uv run python tests/dummy_agents/run_all.py --verbose
```

## What's Tested

| Agent | Tests | What it covers |
|-------|-------|----------------|
| echo | 2 | Single-node lifecycle, basic set_output |
| pipeline | 4 | Multi-node traversal, input_mapping, conversation modes |
| branch | 3 | Conditional edges, LLM-driven routing |
| parallel_merge | 4 | Fan-out/fan-in, failure strategies |
| retry | 4 | Retry mechanics, exhaustion, ON_FAILURE edges |
| feedback_loop | 3 | Feedback cycles, max_node_visits |
| worker | 5 | Real MCP tools plus a two-worker artifact round-trip smoke test |

## Notes

- Tests are **auto-skipped** in regular `pytest` runs (no LLM configured)
- Worker tests start the `hive-tools` MCP server as a subprocess
- Typical runtime: ~1-3 min depending on provider
