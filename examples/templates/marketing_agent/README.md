# Template: Marketing Content Agent

A multi-channel marketing content generator. Given a product and audience, this agent analyzes the audience, generates tailored copy for multiple channels with A/B variants, and reviews the output for quality.

## Workflow

```
[analyze-audience] → [generate-content] → [review-and-refine]
                                                |
                                           (conditional)
                                                |
                               needs_revision == True → [generate-content]
                               needs_revision == False → (done)
```

## Nodes

| Node | Type | Description |
|------|------|-------------|
| `analyze-audience` | `llm_generate` | Produces structured audience analysis |
| `generate-content` | `llm_generate` | Creates per-channel copy with A/B variants |
| `review-and-refine` | `llm_generate` | Reviews and optionally revises content |

## Usage

```bash
# From the repo root
uv run python -m examples.templates.marketing_agent

# With custom input
uv run python -m examples.templates.marketing_agent --input '{
  "product_description": "A fitness tracking app",
  "target_audience": "Health-conscious millennials",
  "brand_voice": "Energetic and motivational",
  "channels": ["instagram", "email"]
}'
```

## Customization ideas

- Add a `function` node to call an analytics API and inform audience analysis with real data
- Add a `human_input` pause node before final output for editorial approval
- Swap `llm_generate` nodes to `llm_tool_use` and add web search tools for competitive research
- Add an image generation tool to produce visual assets alongside copy

## File structure

```
marketing_agent/
├── __init__.py       # Package exports
├── __main__.py       # CLI entry point
├── agent.py          # Goal, edges, graph spec, MarketingAgent class
├── config.py         # RuntimeConfig and AgentMetadata
├── nodes/
│   └── __init__.py   # NodeSpec definitions
└── README.md         # This file
```
