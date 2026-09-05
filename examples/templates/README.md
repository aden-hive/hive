# Templates

A template is a working agent scaffold that follows the standard Hive export structure. Copy it, rename it, customize the goal/nodes/edges, and run it.

## What's in a template

Each template is a complete agent package:

```
template_name/
├── __init__.py       # Package exports
├── __main__.py       # CLI entry point
├── agent.py          # Goal, edges, graph spec, agent class
├── agent.json        # Agent definition (used by build-from-template)
├── config.py         # Runtime configuration
├── nodes/
│   └── __init__.py   # Node definitions (NodeSpec instances)
└── README.md         # What this template demonstrates
```

## How to use a template

### Option 1: Build from template (recommended)

Use the `files-tools` `initialize_and_build_agent` tool and select "From a template" to interactively pick a template, customize the goal/nodes/graph, and export a new agent.

### Option 2: Manual copy

```bash
# 1. Copy to your exports directory
cp -r examples/templates/deep_research_agent exports/my_research_agent

# 2. Update the module references in __main__.py and __init__.py

# 3. Customize goal, nodes, edges, and prompts

# 4. Run it
uv run python -m exports.my_research_agent --input '{"topic": "..."}'
```

## Available templates

| Template | Description |
|----------|-------------|
| [competitive_intel_agent](competitive_intel_agent/) | Monitors competitor websites, news sources, and GitHub repositories to deliver structured digests with key insights and trend analysis |
| [deep_research_agent](deep_research_agent/) | Interactive research agent that searches diverse sources, evaluates findings with user checkpoints, and produces a cited HTML report |
| [email_inbox_management](email_inbox_management/) | Manages Gmail inbox with user-defined free-text rules — trashes junk, marks spam/important, archives, stars, and categorizes for reporting |
| [job_hunter](job_hunter/) | Analyzes a resume to identify strongest role fits, finds matching job opportunities, and generates resume tweaks plus cold outreach for the jobs the user selects |
| [local_business_extractor](local_business_extractor/) | Finds local businesses on Google Maps, scrapes contact details, and syncs to Google Sheets |
| [sdr_agent](sdr_agent/) | Scores contacts by priority, filters suspicious profiles, drafts personalized outreach, and creates Gmail drafts with human review before sending |
| [tech_news_reporter](tech_news_reporter/) | Researches the latest technology and AI news from the web and produces a well-organized report |
| [twitter_news_agent](twitter_news_agent/) | Monitors tech Twitter profiles, extracts the latest tweets, and compiles a daily tech news digest with user review |
| [vulnerability_assessment](vulnerability_assessment/) | Performs passive, OSINT-based security scanning on a target domain and produces letter-grade risk scores (A–F) with a developer-focused report |
