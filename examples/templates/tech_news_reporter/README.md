# Tech & AI News Reporter

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: 2026-02-06

## Overview

Research the latest technology and AI news from the web, summarize key stories, and produce a well-organized report for the user to read.

## Architecture

### Execution Flow

```
intake → research → compile-report
```

### Nodes (3 total)

1. **intake** (event_loop)
   - Greet the user and ask if they have specific tech/AI topics to focus on, or if they want a general news roundup.
   - Writes: `research_brief`
   - Client-facing: Yes (blocks for user input)
2. **research** (event_loop)
   - Search the web for recent tech/AI news articles, scrape the top results, and extract key information including titles, summaries, sources, and topics.
   - Reads: `research_brief`
   - Writes: `articles_data`
   - Tools: `web_search, web_scrape`
3. **compile-report** (event_loop)
   - Organize the researched articles into a structured HTML report, save it, and deliver a clickable link to the user.
   - Reads: `articles_data`
   - Writes: `report_file`
   - Tools: `save_data, serve_file_to_user`
   - Client-facing: Yes (blocks for user input)

### Edges (2 total)

- `intake` → `research` (condition: on_success, priority=1)
- `research` → `compile-report` (condition: on_success, priority=1)


## Goal Criteria

### Success Criteria

**Finds recent, relevant tech/AI news articles** (weight 0.25)
- Metric: Number of articles sourced
- Target: 5+ articles
**Covers diverse topics, not just one story** (weight 0.2)
- Metric: Distinct topics covered
- Target: 3+ topics
**Produces a structured, readable report with sections, summaries, and links** (weight 0.25)
- Metric: Report has clear sections and summaries
- Target: Yes
**Includes source attribution with URLs for every story** (weight 0.15)
- Metric: Stories with source URLs
- Target: 100%
**Delivers the report to the user in a viewable format** (weight 0.15)
- Metric: User receives a viewable report
- Target: Yes

### Constraints

**Never fabricate news stories or URLs** (hard)
- Category: quality
**Always attribute sources with links** (hard)
- Category: quality
**Only include news from the past week** (hard)
- Category: quality

## Required Tools

- `save_data`
- `serve_file_to_user`
- `web_scrape`
- `web_search`







## Usage

Run the agent from the `examples/templates` directory:

```bash
cd examples/templates

# Interactive session (recommended) — the agent asks which news you want
uv run python -m tech_news_reporter shell

# One-shot run — prints the result as JSON
uv run python -m tech_news_reporter run

# Other commands
uv run python -m tech_news_reporter info       # show agent details
uv run python -m tech_news_reporter validate   # validate agent structure
uv run python -m tech_news_reporter tui        # launch the TUI dashboard
```

### Example

This agent is interactive: the `intake` node greets you and asks which tech/AI
topics to cover, so you provide your request at the prompt rather than as a
JSON payload.

**Sample input** (your answer when the agent asks what to cover):

```text
Latest large language model and semiconductor news from the past week
```

**Sample output** (`run` command, abbreviated):

```json
{
  "success": true,
  "steps_executed": 3,
  "output": {
    "report_file": "tech_news_report.html"
  }
}
```

The agent saves a structured HTML report (`tech_news_report.html`) and opens it
in your default browser. The report groups the sourced articles by topic, with
a short summary and a source link for each story.

### Input Schema

The entry node `intake` takes no structured input (`input_keys: []`). Instead it
prompts you interactively for the topics you want covered and derives an internal
`research_brief` from your answer. To get the default general tech & AI roundup,
just press Enter without specifying a topic.

### Output Schema

The terminal node `compile-report` produces `report_file`, the filename of the
generated HTML report. The CLI wraps this in an `ExecutionResult`:

| Field                | Type | Description                                  |
| -------------------- | ---- | -------------------------------------------- |
| `success`            | bool | Whether the run met its goal criteria        |
| `steps_executed`     | int  | Number of nodes executed                     |
| `output.report_file` | str  | Filename of the saved HTML report            |
| `error`              | str  | Present only if the run failed               |

## Version History

- **1.0.0** (2026-02-06): Initial release
  - 3 nodes, 2 edges
  - Goal: Tech & AI News Reporter
