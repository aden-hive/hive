# Deep Research Agent

A template agent designed to perform comprehensive, multi-source research on a topic and generate a structured report. Supports interactive TUI conversations, a CLI shell, and non-interactive batch mode.

## Prerequisites

- **Python 3.11+** with `uv`
- **LLM API key** — set one of:
  - `ANTHROPIC_API_KEY` (default provider)
  - `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc. (see [configuration guide](../../../docs/configuration.md))
- **BRAVE_SEARCH_API_KEY** *(optional)* — for live web search; omit to use cached/mock results

## Quick Start

```bash
# From the repository root
export ANTHROPIC_API_KEY="sk-ant-..."
export BRAVE_SEARCH_API_KEY="..."    # optional

# Run a research session (interactive conversation)
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent run --topic "Quantum computing in 2025"
```

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:PYTHONPATH = "core;examples\templates"
uv run python -m deep_research_agent run --topic "Quantum computing in 2025"
```

## Available Commands

| Command | Description |
|---------|-------------|
| `run --topic "..."` | Research a topic (interactive HITL conversation) |
| `shell` | Interactive research REPL — enter topics one by one |
| `tui` | Launch the full TUI dashboard |
| `info` | Print agent metadata (nodes, entry point, version) |
| `validate` | Validate the agent graph structure |

### Run options

```bash
# Basic research run
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent run --topic "Rust vs Go"

# Verbose output (show execution steps)
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent run --topic "Rust vs Go" --verbose

# JSON-only output (for scripting)
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent run --topic "Rust vs Go" --quiet

# Interactive REPL
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent shell

# Agent info
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent info
PYTHONPATH=core:examples/templates uv run python -m deep_research_agent info --json
```

## What the Agent Does

1. **Intake** — Asks clarifying questions to sharpen the research brief
2. **Search** — Runs multiple web searches across diverse sources
3. **Evaluate** — Scores source quality and filters low-quality results
4. **Synthesize** — Merges findings into a coherent draft
5. **Report** — Delivers a structured Markdown report with citations

## Example Output

```json
{
  "success": true,
  "steps_executed": 12,
  "output": {
    "report_file": "~/.hive/agents/deep_research_agent/sessions/.../report.md",
    "delivery_status": "delivered"
  }
}
```

## Input Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | ✅ | The research topic or question |

## Output Schema

| Field | Type | Description |
|-------|------|-------------|
| `report_file` | string | Path to the generated Markdown report |
| `delivery_status` | string | `"delivered"` on success |
| `research_brief` | string | Refined research brief (from intake node) |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Missing ANTHROPIC_API_KEY` | Set the env var or configure another provider in `~/.hive/configuration.json` |
| Web search returns no results | Set `BRAVE_SEARCH_API_KEY` or use `EXA_API_KEY` |
| `ModuleNotFoundError: framework` | Make sure `PYTHONPATH=core:examples/templates` is set |
| TUI fails with import error | Install textual: `uv pip install textual` |
