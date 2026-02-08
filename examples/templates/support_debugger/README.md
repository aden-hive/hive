# Support Debugger Agent

Hypothesis-driven investigation agent for technical support tickets. Given a support ticket, this agent extracts technical context, generates competing root-cause hypotheses, gathers evidence through investigative tools, refines confidence scores, and produces a structured resolution with actionable fix steps.

## What it does

1. **Build Context** — Extracts product, platform, framework, and language from the ticket
2. **Generate Hypotheses** — Produces 3–5 competing root-cause hypotheses with confidence scores
3. **Investigate** — Calls tools to gather evidence for/against each hypothesis
4. **Refine Hypotheses** — Updates confidence scores based on evidence; decides whether to loop
5. **Generate Response** — Produces a final root-cause analysis with fix steps and validation steps

The investigation loop (steps 3–4) repeats until the top hypothesis reaches ≥ 0.9 confidence with sufficient separation from alternatives, or the iteration limit is reached.

## Architecture

```
[build-context] → [generate-hypotheses] → [investigate] → [refine-hypotheses]
                                               ↑                    │
                                               │            (conditional)
                                               │                    │
                                               └── incomplete ──────┘
                                                                    │
                                                               complete
                                                                    ↓
                                                         [generate-response]
```

### How the loop works

The `refine-hypotheses` node evaluates two stop conditions after each evidence-gathering round:

1. **Top hypothesis confidence ≥ 0.9**
2. **Gap between top and second hypothesis ≥ 0.15**

When both conditions are met, `investigation_complete` is set to `True` and execution routes to `generate-response`. Otherwise, it loops back to `investigate` for another evidence-gathering round.

The `investigate` node has `max_node_visits=5`, providing a hard upper bound on loop iterations.

## Nodes

| Node | Type | Purpose | Inputs | Outputs |
|------|------|---------|--------|---------|
| `build-context` | `event_loop` | Extract technical context from ticket | `ticket` | `technical_context` |
| `generate-hypotheses` | `event_loop` | Generate competing root-cause hypotheses | `ticket`, `technical_context` | `hypotheses` |
| `investigate` | `event_loop` | Call tools to gather evidence | `ticket`, `hypotheses`, `technical_context` | `evidence` |
| `refine-hypotheses` | `event_loop` | Update confidence scores, check stop condition | `hypotheses`, `evidence` | `hypotheses`, `investigation_complete` |
| `generate-response` | `event_loop` | Produce final resolution | `ticket`, `hypotheses`, `evidence`, `technical_context` | `final_response` |

## Usage

All commands are run from the `hive/` directory.

```bash
# Validate agent structure
uv run python -m examples.templates.support_debugger validate

# Show agent info (nodes, edges, entry/terminal)
uv run python -m examples.templates.support_debugger info

# Run in mock mode — no API keys required
uv run python -m examples.templates.support_debugger run \
  --mock --ticket examples/templates/support_debugger/samples/python_pytest_zero_tests.json

# Run with a real LLM (requires API key configured)
uv run python -m examples.templates.support_debugger run \
  --ticket examples/templates/support_debugger/samples/python_pytest_zero_tests.json

# Verbose output
uv run python -m examples.templates.support_debugger run \
  --mock --verbose --ticket examples/templates/support_debugger/samples/selenium_timeout_android.json
```

## Input format

The agent accepts a JSON file matching the `TicketInput` schema:

```json
{
  "subject": "Short summary of the issue",
  "description": "Detailed description with technical context, error messages, environment info, and steps to reproduce."
}
```

The `description` field should include as much technical detail as possible — error messages, stack traces, configuration details, versions, and environment information all improve hypothesis quality.

Sample tickets are provided in `samples/`.

## Output format

The agent produces a `FinalResponse` with this structure:

```json
{
  "root_cause": "Identified root cause of the issue",
  "explanation": "Technical explanation of why the issue occurs",
  "fix_steps": [
    "Step 1: Specific actionable instruction",
    "Step 2: Next instruction"
  ],
  "config_snippet": "key: value\nother_key: value",
  "validation_steps": [
    "Verify that the fix resolves the reported behavior"
  ],
  "confidence": 0.92
}
```

The full execution result (returned by the CLI) also includes `success`, `steps_executed`, and intermediate state accumulated during investigation.

## Tools

The `investigate` node has access to three tools. The current implementations are **reference stubs** that return hardcoded data — they are designed as extension points for real integrations.

| Tool | Description | Replace with |
|------|-------------|--------------|
| `search_knowledge_base(query)` | Search product docs and KB articles | Vector search, Confluence API, docs index |
| `fetch_ticket_history(keywords)` | Fetch resolved tickets with similar issues | Freshdesk API, BigQuery, Zendesk |
| `fetch_runtime_logs(session_id)` | Fetch runtime logs for a session or build | Log aggregator, CloudWatch, Datadog |

Tools are discovered automatically by `ToolRegistry.discover_from_module()` via the `@tool` decorator in `tools.py`.

## Customization ideas

- **Replace tool implementations** — Edit `tools.py` to connect real backends. Keep the function signatures and return shapes identical; the prompts reference specific output fields.
- **Add new tools** — Add `@tool`-decorated functions to `tools.py` and add the tool name to the `investigate` node's `tools` list in `nodes/__init__.py`. Update the investigate prompt to reference the new tool.
- **Adjust convergence logic** — Edit the confidence thresholds (0.9 top, 0.15 gap) in the `refine-hypotheses` prompt to be more or less aggressive.
- **Modify hypothesis categories** — Edit the allowed categories list (`app`, `test`, `config`, `dependency`, `network`, `infra`) in the `generate-hypotheses` prompt.
- **Add a human-in-the-loop node** — Insert a pause node between `refine-hypotheses` and `generate-response` for manual review before final response generation.
- **Add new evidence sources** — Create additional tools for Slack search, JIRA queries, or code repository search to broaden the investigation scope.
- **Swap the LLM** — Edit `config.py` to change `model` to any LiteLLM-compatible model string.

## Testing

```bash
# Run all support_debugger tests
cd hive && uv run pytest examples/templates/support_debugger/tests/ -v

# Run as part of the full test suite
make test
```

Tests are fully deterministic — they use `DummyRuntime` and fake node implementations, with no real LLM calls or network access.

| Test class | What it validates |
|------------|-------------------|
| `TestValidation` | `validate()` passes with no errors or warnings |
| `TestGraphTopology` | 5 nodes, 5 edges, entry/terminal correctness, tool wiring, reachability |
| `TestRunMock` | Full graph execution with fake nodes completes successfully |
| `TestLoopTermination` | Loop exits on convergence; iterates when incomplete |
| `TestEdgeRouting` | Conditional edges route correctly based on `investigation_complete` |

## Limitations

- **No automatic learning** — The agent does not learn from past investigations. Each run starts fresh.
- **Tool quality dependency** — Investigation quality is bounded by what the tools return. The reference stubs return hardcoded data; real integrations are required for production value.
- **Single-ticket scope** — The agent investigates one ticket at a time. Cross-ticket pattern detection is not implemented.
- **No HITL** — There is currently no human-in-the-loop review step before response generation.
- **Mock mode limitations** — `MockLLMProvider` does not produce structured outputs, so mock runs demonstrate the execution flow but not realistic reasoning.

## Roadmap

These are planned for follow-up PRs:

- **Real tool integrations** — Connect `search_knowledge_base`, `fetch_ticket_history`, and `fetch_runtime_logs` to production backends (BigQuery, Freshdesk, log aggregators)
- **MCP tool server** — Expose tools as an MCP server for cross-agent reuse
- **Observability** — Add `Runtime.decide()` and `record_outcome()` calls for decision tracing and analytics
- **Human-in-the-loop** — Add a pause node for agent response review before delivery
- **TUI support** — Add `tui` and `shell` CLI commands via `AgentRuntime`
- **Multi-ticket patterns** — Aggregate investigation results across related tickets
- **BuilderQuery integration** — Enable self-improvement via outcome analysis

## Contributing

Contributions are welcome. Please follow the guidelines in [CONTRIBUTING.md](../../../CONTRIBUTING.md):

1. Claim an issue before submitting a PR
2. Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
3. Ensure `make check` and `make test` pass
4. Add tests for new functionality

## File structure

```
support_debugger/
├── __init__.py         # Package exports
├── __main__.py         # CLI entry point (validate, info, run)
├── agent.py            # Goal, edges, graph spec, SupportDebuggerAgent class
├── config.py           # RuntimeConfig and AgentMetadata
├── models.py           # Pydantic domain models (TicketInput, Hypothesis, etc.)
├── tools.py            # @tool-decorated reference implementations
├── nodes/
│   └── __init__.py     # NodeSpec definitions with prompts
├── samples/            # Example ticket inputs
│   ├── python_pytest_zero_tests.json
│   ├── selenium_timeout_android.json
│   └── ci_flaky_parallel_tests.json
├── tests/
│   ├── conftest.py     # Test path setup
│   ├── fixtures/
│   │   └── sample_ticket.json
│   └── test_support_debugger.py
└── README.md           # This file
```
