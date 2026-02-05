# Examples

This directory contains two types of examples to help you build agents with the Hive framework.

## Recipes vs Templates

### [recipes/](recipes/) — "How to make it"

A recipe is a **prompt-only** description of an agent. It tells you the goal, the nodes, the prompts, the edge routing logic, and what tools to wire in — but it's not runnable code. You read the recipe, then build the agent yourself.

Use recipes when you want to:
- Understand a pattern before committing to an implementation
- Adapt an idea to your own codebase or tooling
- Learn how to think about agent design (goals, nodes, edges, prompts)

### [templates/](templates/) — "Ready to eat"

A template is a **working agent scaffold** that follows the standard Hive export structure. Copy the folder, rename it, swap in your own prompts and tools, and run it.

Use templates when you want to:
- Get a new agent running quickly
- Start from a known-good structure instead of from scratch
- See how all the pieces (goal, nodes, edges, config, CLI) fit together in real code

## How to use a template

```bash
# 1. Copy the template
cp -r examples/templates/marketing_agent exports/my_agent

# 2. Edit the goal, nodes, and edges in agent.py and nodes/__init__.py

# 3. Run it
uv run python -m exports.my_agent --help
```

## How to use a recipe

1. Read the recipe markdown file
2. Use the patterns described to build your own agent — either manually or with the builder agent (`/agent-workflow`)
3. Refer to the [core README](../core/README.md) for framework API details
