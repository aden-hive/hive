# Competitive Intelligence Agent (Community) 
## Built by https://github.com/nafiyad

An autonomous agent that monitors competitor websites, news sources, and GitHub repositories to deliver structured digests with key insights and trend analysis.

## Prerequisites

- **Python 3.11+** with `uv`
- **ANTHROPIC_API_KEY** — set in your `.env` or environment
- **GITHUB_TOKEN** *(optional)* — for GitHub activity monitoring

## Quick Start

### Interactive Shell
```bash
cd examples/templates
uv run python -m competitive_intel_agent shell
```

### CLI Run
```bash
# With inline JSON
uv run python -m competitive_intel_agent run \
  --competitors '[{"name":"Acme","website":"https://acme.com","github":"acme-org"},{"name":"Beta Inc","website":"https://beta.io","github":null}]' \
  --focus-areas "pricing,features,partnerships,hiring" \
  --frequency weekly

# From a file
uv run python -m competitive_intel_agent run --competitors competitors.json
```

### TUI Dashboard
```bash
uv run python -m competitive_intel_agent tui
```

### Validate & Info
```bash
uv run python -m competitive_intel_agent validate
uv run python -m competitive_intel_agent info
```

## Agent Graph

```
intake → web-scraper → news-search → github-monitor → aggregator → analysis → report
                                           ↑
                         (skipped if no competitors have GitHub)
```

| Node | Purpose | Tools | Client-Facing |
|------|---------|-------|:---:|
| **intake** | Collect competitor list & focus areas | — | ✅ |
| **web-scraper** | Scrape competitor websites | web_search, web_scrape | |
| **news-search** | Search news & press releases | web_search, web_scrape | |
| **github-monitor** | Track public GitHub activity | github_* | |
| **aggregator** | Merge, deduplicate, persist | save_data, load_data | |
| **analysis** | Extract insights & trends | load_data, save_data | |
| **report** | Generate HTML digest | save_data, serve_file | ✅ |

## Input Format

```json
{
  "competitors": [
    {"name": "CompetitorA", "website": "https://competitor-a.com", "github": "competitor-a"},
    {"name": "CompetitorB", "website": "https://competitor-b.com", "github": null}
  ],
  "focus_areas": ["pricing", "new_features", "hiring", "partnerships"],
  "report_frequency": "weekly"
}
```

## Output

The agent produces an HTML report saved to `~/.hive/agents/competitive_intel_agent/` with:
- 🔥 **Key Highlights** — most significant competitive moves
- 📊 **Per-Competitor Tables** — category, update, source, date
- 📈 **30-Day Trends** — patterns across competitors over time

Historical snapshots are stored for trend comparison on subsequent runs.
