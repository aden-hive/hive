# Recipes

A recipe describes an agent's design — the goal, nodes, prompts, edge logic, and tools — without providing runnable code. Think of it as a blueprint: it tells you *how* to build the agent, but you do the building.

## What's in a recipe

Each recipe is a markdown file (or folder with a markdown file) containing:

- **Goal**: What the agent accomplishes, including success criteria and constraints
- **Nodes**: Each step in the workflow, with the system prompt, node type, and input/output keys
- **Edges**: How nodes connect, including conditions and routing logic
- **Tools**: What external tools or MCP servers the agent needs
- **Usage notes**: Tips, gotchas, and suggested variations

## How to use a recipe

1. Read through the recipe to understand the design
2. Create a new agent using the standard export structure (see [templates/](../templates/) for a scaffold)
3. Translate the recipe's goal, nodes, and edges into code
4. Wire in the tools described
5. Test and iterate

## Available recipes

| Recipe | Description |
|--------|-------------|
| [marketing_agent](marketing_agent/) | Multi-channel marketing content generator with audience analysis and A/B copy variants |
