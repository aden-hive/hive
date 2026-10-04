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

## Quick Decision Guide

| If your goal is... | Start with | Why |
| --- | --- | --- |
| Learn agent design patterns before coding | [`recipes/`](recipes/) | Recipes show goals, prompts, and routing logic without implementation details |
| Get something runnable in minutes | [`templates/`](templates/) | Templates are executable scaffolds you can copy and run |
| Customize behavior for your own system | [`templates/`](templates/) | You can edit prompts, tools, and node logic in working code |
| Understand trade-offs across multiple approaches | [`recipes/`](recipes/) | Recipes are easier to compare side-by-side before committing to code |
| Onboard a new contributor quickly | [`templates/`](templates/) | A runnable baseline reduces setup and architecture guesswork |

## Starter Recommendations

- **First runnable agent:** start with [`templates/email_inbox_management/`](templates/email_inbox_management/) for a practical end-to-end flow.
- **Research-oriented workflows:** use [`templates/deep_research_agent/`](templates/deep_research_agent/) to learn multi-step reasoning and synthesis patterns.
- **Security and analysis style tasks:** explore [`templates/vulnerability_assessment/`](templates/vulnerability_assessment/) for structured investigation workflows.
- **Pattern learning before coding:** read [`recipes/support_troubleshooting/`](recipes/support_troubleshooting/), then implement your own variant.
- **If you are still unsure:** pick one recipe to understand the design, then move to the closest template and run it.

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
2. Use the patterns described to build your own agent — either manually or with the builder agent (`/hive`)
3. Refer to the [core README](../core/README.md) for framework API details
