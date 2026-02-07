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
cp -r examples/templates/marketing_agent exports/my_marketing_agent

# 2. Update the module references in __main__.py and __init__.py

# 3. Customize goal, nodes, edges, and prompts

# 4. Run it
uv run python -m exports.my_marketing_agent --input '{"product_description": "..."}'
```

## Available templates

| Template | Description |
|----------|-------------|
| [marketing_agent](marketing_agent/) | Multi-channel marketing content generator with audience analysis, content generation, and editorial review nodes |
