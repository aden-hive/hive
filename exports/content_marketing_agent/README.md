# Content Marketing Agent

Automatically creates and publishes blog posts based on company news with human approval workflow.

## Features

- **News Monitoring**: Monitors RSS feeds/webhooks for company news
- **Content Writing**: Generates engaging, brand-aligned blog posts
- **Quality Review**: Validates factual accuracy, SEO, and brand voice
- **Human Approval**: HITL checkpoint before publishing
- **Self-Improvement**: Learns from rejection feedback via LTM

## Quick Start

```bash
# Validate agent structure
PYTHONPATH=core:exports python -m content_marketing_agent validate

# Show agent info
PYTHONPATH=core:exports python -m content_marketing_agent info

# Run with a news item
PYTHONPATH=core:exports python -m content_marketing_agent run \
  --title "Acme Corp Announces Q4 Earnings" \
  --summary "Acme Corp reported record earnings of $2.5B in Q4 2025..."

# Run in mock mode (no LLM calls)
PYTHONPATH=core:exports python -m content_marketing_agent run --mock \
  --title "Test News" --summary "Test summary"
```

## Architecture

```
┌─────────────────┐
│  News Monitor   │ → Filters and extracts news
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Content Writer  │ → Generates blog draft
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Quality Review  │ → Validates quality (0-1 score)
└────────┬────────┘
         │
    ┌────┴────┐
    │ Router  │ → quality >= 0.7?
    └────┬────┘
    YES  │  NO → back to Content Writer
         ▼
┌─────────────────┐
│ Human Approval  │ → HITL checkpoint
└────────┬────────┘
         │
    ┌────┴────┐
    │ Router  │ → approved?
    └────┬────┘
    YES  │  NO → Feedback Learner → back to Writer
         ▼
┌─────────────────┐
│   Publisher     │ → Publishes to WordPress
└─────────────────┘
```

## Configuration

Environment variables:
- `ANTHROPIC_API_KEY` - Required for LLM calls
- `WORDPRESS_URL` - WordPress site URL (optional)
- `WORDPRESS_TOKEN` - WordPress API token (optional)

## Testing

```bash
# Run tests
PYTHONPATH=core:exports python -m pytest exports/content_marketing_agent/tests/
```

## Files

- `agent.py` - Agent graph definition (nodes, edges, goal)
- `nodes.py` - Node specifications
- `tools.py` - Custom tool implementations
- `config.py` - Configuration settings
- `__main__.py` - CLI entry point
