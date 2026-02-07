# Deep Research Agent

**Version**: 1.0.0
**Type**: Multi-node agent with feedback loop
**Created**: 2026-02-06

## Overview

Research any topic by searching diverse sources, analyzing findings, and producing a cited report — with user checkpoints to guide direction. The agent features a feedback loop between review and research, allowing iterative deepening until the user is satisfied with the coverage and quality of findings.

## Business Value

- **Research automation** — Reduces hours of manual web research into a single guided session, freeing analysts to focus on synthesis and decision-making
- **Quality assurance** — Built-in review checkpoint ensures findings meet user expectations before report generation, preventing wasted effort on misaligned research
- **Iterative deepening** — Feedback loop between review and research allows progressive refinement without restarting, matching how expert researchers work
- **Citation compliance** — Every factual claim requires source attribution, producing reports that meet academic and professional standards out of the box
- **Reusable pattern** — The intake-research-review-report architecture with conditional feedback loop serves as a foundation for any investigation workflow

## Architecture

### Execution Flow

```
intake → research → review → report
                      ↓  ↑
                  feedback loop
              (if needs more research)
```

### Nodes (4 total)

1. **intake** (`event_loop`)
   - Discuss the research topic with the user, clarify scope, and confirm direction
   - Reads: `topic`
   - Writes: `research_brief`
   - Tools: none
   - Client-facing: Yes

2. **research** (`event_loop`)
   - Search the web, fetch source content, and compile findings
   - Reads: `research_brief`, `feedback`
   - Writes: `findings`, `sources`, `gaps`
   - Tools: `web_search`, `web_scrape`, `load_data`, `save_data`, `list_data_files`
   - Client-facing: No
   - Max visits: 3

3. **review** (`event_loop`)
   - Present findings to user and decide whether to research more or write the report
   - Reads: `findings`, `sources`, `gaps`, `research_brief`
   - Writes: `needs_more_research`, `feedback`
   - Tools: none
   - Client-facing: Yes
   - Max visits: 3

4. **report** (`event_loop`)
   - Write a cited HTML report from the findings and present it to the user
   - Reads: `findings`, `sources`, `research_brief`
   - Writes: `delivery_status`
   - Tools: `save_data`, `serve_file_to_user`, `load_data`, `list_data_files`
   - Client-facing: Yes

### Edges (4 total)

- `intake` → `research` (condition: `on_success`, priority 1)
- `research` → `review` (condition: `on_success`, priority 1)
- `review` → `research` (condition: `needs_more_research == True`, priority 1) — feedback loop
- `review` → `report` (condition: `needs_more_research == False`, priority 2)

## Goal Criteria

### Success Criteria

**Source diversity** (weight 0.25)
- Metric: `source_count`
- Target: >= 5 diverse, authoritative sources

**Citation coverage** (weight 0.25)
- Metric: `citation_coverage`
- Target: 100% — every factual claim cites its source

**User satisfaction** (weight 0.25)
- Metric: `user_approval`
- Target: User reviews findings before report generation

**Report completeness** (weight 0.25)
- Metric: `question_coverage`
- Target: 90% — final report answers the original research questions

### Constraints

- **No hallucination** (quality/accuracy) — Only include information found in fetched sources
- **Source attribution** (quality/accuracy) — Every claim must cite its source with a numbered reference
- **User checkpoint** (functional/interaction) — Present findings to the user before writing the final report

## Required Tools

The agent uses tools provided by the Hive MCP server:

- `web_search` — Search the web with diverse queries across different angles
- `web_scrape` — Fetch and extract content from promising source URLs
- `save_data` — Persist research findings and the final HTML report
- `load_data` — Retrieve previously saved research data
- `list_data_files` — Browse saved data files
- `serve_file_to_user` — Deliver the final report as a clickable link

## Usage

```bash
# Validate the agent structure
PYTHONPATH=core:exports uv run python -m deep_research_agent validate

# Show agent info
PYTHONPATH=core:exports uv run python -m deep_research_agent info

# Run research on a topic
PYTHONPATH=core:exports uv run python -m deep_research_agent run --topic "quantum computing breakthroughs 2025"

# Launch the TUI for interactive research
PYTHONPATH=core:exports uv run python -m deep_research_agent tui

# Interactive shell
PYTHONPATH=core:exports uv run python -m deep_research_agent shell
```

### Programmatic Usage

```python
import asyncio
from deep_research_agent import DeepResearchAgent

async def main():
    agent = DeepResearchAgent()
    result = await agent.run({"topic": "impact of AI on healthcare diagnostics"})
    if result.success:
        print("Research complete:", result.output)
    else:
        print("Failed:", result.error)

asyncio.run(main())
```

## Customization Guide

### Adjusting Research Depth

Modify the `max_node_visits` on `research_node` and `review_node` in `nodes/__init__.py` to control how many feedback iterations are allowed. The default is 3 visits each.

### Changing the Model

Edit `config.py` to change the default model. The agent reads from `~/.hive/configuration.json` if available, falling back to `anthropic/claude-sonnet-4-20250514`.

### Adding Custom Tools

Add tool names to the `tools` list in any `NodeSpec` in `nodes/__init__.py`. Register the corresponding tool implementations in your MCP server or tool registry.

### Modifying Report Format

Edit the `report_node` system prompt in `nodes/__init__.py` to change the HTML structure, styling, or report sections. The default produces a self-contained HTML document with executive summary, table of contents, themed findings, and numbered references.

### Adding New Nodes

Define a new `NodeSpec` in `nodes/__init__.py`, add it to the `nodes` list in `agent.py`, and create `EdgeSpec` entries to connect it to the graph. For example, add a fact-checking node between `review` and `report` for additional verification.

## Example Output

A successful run produces:
- An interactive intake session where the research scope is clarified
- Multiple rounds of web research with 5+ authoritative sources
- A user review checkpoint with a summary of findings and gaps
- A self-contained HTML report with:
  - Executive summary
  - Table of contents
  - Themed findings with `[n]` citation links
  - Analysis and synthesis section
  - Numbered references with clickable URLs

## MCP Server Configuration

The agent connects to the Hive tools MCP server. Configuration from `mcp_servers.json`:

```json
{
  "hive-tools": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "mcp_server.py", "--stdio"],
    "cwd": "../../../tools",
    "description": "Hive tools MCP server providing web_search, web_scrape, and write_to_file"
  }
}
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-02-06 | Initial release with 4-node research pipeline and feedback loop |
