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

Use the `coder-tools` `initialize_and_build_agent` tool and select "From a template" to interactively pick a template, customize the goal/nodes/graph, and export a new agent.

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
| [deep_research_agent](deep_research_agent/) | Interactive research agent that searches diverse sources, evaluates findings with user checkpoints, and produces a cited HTML report |
| [local_business_extractor](local_business_extractor/) | Finds local businesses on Google Maps, scrapes contact details, and syncs to Google Sheets |
| [tech_news_reporter](tech_news_reporter/) | Researches the latest technology and AI news from the web and produces a well-organized report |
| [competitive_intel_agent](competitive_intel_agent/) | Monitors competitor websites, news sources, and GitHub repos to deliver structured digests with key insights and trend analysis |
| [email_inbox_management](email_inbox_management/) | Automatically manages Gmail inbox using user-defined free-text rules — trash junk, mark spam, archive, star, and report actions taken |
| [email_reply_agent](email_reply_agent/) | Reads and drafts context-aware replies to emails using customizable tone and response guidelines |
| [job_hunter](job_hunter/) | Searches job boards for matching roles, filters by criteria, and compiles a ranked list of opportunities with application links |
| [meeting_scheduler](meeting_scheduler/) | Coordinates meeting availability across participants and proposes optimal time slots based on calendar constraints |
| [twitter_news_agent](twitter_news_agent/) | Monitors Twitter/X for trending topics and news in a target domain and generates a curated daily digest |
| [vulnerability_assessment](vulnerability_assessment/) | Scans a target codebase or URL for common security vulnerabilities and produces a structured risk report |
