# Templates

A template is a working agent scaffold that follows the standard Hive export structure. Copy it, rename it, customize the goal/nodes/edges, and run it.

## What's in a template

Each template is a complete agent package:

```
template_name/
├── __init__.py       # Package exports
├── __main__.py       # CLI entry point
├── agent.py          # Goal, edges, graph spec, agent class
├── config.py         # Runtime configuration
├── nodes/
│   └── __init__.py   # Node definitions (NodeSpec instances)
└── README.md         # What this template demonstrates
```

## How to use a template

```bash
# 1. Copy to your exports directory
cp -r examples/templates/deep_research_agent exports/my_research_agent

# 2. Update the module references in __main__.py and __init__.py

# 3. Customize goal, nodes, edges, and prompts

# 4. Run it
uv run python -m exports.my_research_agent run --topic "your research topic"
```

## Available templates

| Template | Nodes | Description |
|----------|:-----:|-------------|
| [deep_research_agent](deep_research_agent/) | 4 | Research any topic through multi-source search with user review checkpoints and a feedback loop for iterative deepening. Produces a cited HTML report. |
| [tech_news_reporter](tech_news_reporter/) | 3 | Scan the web for recent tech/AI news, summarize key stories, and deliver a structured HTML report. |
| [twitter_outreach](twitter_outreach/) | 4 | Research a target's Twitter/X profile and craft a personalized outreach email with human approval before sending. |
