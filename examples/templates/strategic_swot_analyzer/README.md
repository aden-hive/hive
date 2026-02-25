# Strategic SWOT Analysis Agent

Built by [Aarav](https://github.com/aarav-shukla07)

An autonomous agent that executes a recursive research graph to dynamically identify market competitors, extract pricing/feature data, and synthesize a formal Strategic SWOT Matrix with historical delta-tracking.

---

## Prerequisites

- **Python 3.11+** with `uv`
- `ANTHROPIC_API_KEY` — set in your `.env` or environment
- `BRAVE_SEARCH_API_KEY` (optional) — for enhanced web discovery

---

## Quick Start

### Ad-Hoc / Fresh Run

Run a fresh analysis on a target company.  
The agent will discover competitors automatically.

```bash
uv run python -m examples.templates.strategic_swot_analyzer run \
  --company "Linear"
```

---

### Scheduled / Cron Run (Delta Tracking)

Simulate a scheduled run.

The agent will load the previous state to highlight strategic shifts  
(e.g., pricing changes) since the last execution.

```bash
uv run python -m examples.templates.strategic_swot_analyzer run \
  --company "Linear" \
  --cron
```

---

### Validate Graph

```bash
uv run python -m examples.templates.strategic_swot_analyzer validate
```

---

## Agent Graph

```
identify-competitors → research-competitors → synthesize-swot → report-results
```

---

## Nodes

| Node | Purpose | Tools | Client-Facing |
|------|---------|------|---------------|
| identify-competitors | Discover top 3 market rivals | web_search |  |
| research-competitors | Scrape pricing and feature data | web_search, web_scrape |  |
| synthesize-swot | Build matrix & calculate deltas | — |  |
| report-results | Format and persist Markdown | save_data | ✅ |

---

## Input Format

The agent primarily requires a target company.  
For recurring runs, a previous state summary is injected.

```json
{
  "target_company": "Linear",
  "previous_run_summary": "Last week: Asana launched AI timeline features."
}
```

---

## Output

The agent produces a comprehensive Markdown report saved to the local:

```
agent_storage/
```

The report contains:

- 🎯 Competitive Landscape — Identified rivals and URLs.
- 🧠 SWOT Matrix — Strengths, Weaknesses, Opportunities, and Threats based on live data.
- 📈 Strategic Deltas — Highlighted changes in competitor positioning compared to the previous run.