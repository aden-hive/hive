# Goal Decomposition Preview Guide

Hive allows you to visualize and refine your agent's architecture before writing a single line of code. This "Goal Preview" feature uses an LLM to decompose your high-level goal into a graph of nodes and edges, identify potential risks, and estimate costs.

## Quick Start

Run the preview command with a goal description:

```bash
hive preview "Create a market research agent that finds competitors for a given product."
```

## Preview Output

The preview generates:

1.  **Likely Nodes**: The steps the agent will take (e.g., `CompetitorSearch`, `DataAnalysis`, `ReportGeneration`).
2.  **Flow Logic**: How data moves between nodes (e.g., `Search -> Analysis`).
3.  **Risk Analysis**: Potential pitfalls (e.g., "Ambiguous success criteria").
4.  **Cost & Complexity Estimates**: Rough dollar amount for generation and execution.

## Interactive Refinement

After viewing the preview, you can:

*   **[y] Proceed**: Generate the agent scaffold code based on the preview.
*   **[r] Refine Goal**: Update your goal description to steer the architecture (e.g., "Add a node to checking specific social media sites").
*   **[n] Cancel**: Exit without generating files.

## Command Reference

```bash
hive preview [GOAL_DESCRIPTION] [OPTIONS]
```

**Options:**

*   `--name`: Name of the agent (default: "preview-agent").
*   `--criteria`: Comma-separated success criteria (e.g., "Must find 5 competitors, Must include pricing").

## Example

```bash
hive preview "Build a personal shopper agent" \
  --name "ShopperBot" \
  --criteria "Finds lowest price, Checks delivery time"
```
