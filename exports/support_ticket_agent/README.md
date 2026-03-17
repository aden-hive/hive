# Support Ticket Agent

**Version**: 1.0.0  
**Type**: Multi-node agent (3 nodes, linear graph)  
**Created**: 2026-01-29

## Overview

Minimal example agent demonstrating the Hive framework's core features. This agent processes customer support tickets through a three-step pipeline: parse → categorize → generate response.

**Purpose**: This agent serves as the canonical reference for:
- Basic agent structure and file organization
- Three-node linear graph execution
- LLM-only nodes (no external tool dependencies)
- Mock mode testing without API keys
- CLI interface using AgentRunner

## Architecture

### Execution Flow

```
parse-ticket → categorize-issue → generate-response
```

### Nodes (3 total)

1. **parse-ticket** (llm_generate)
   - Extract key information from the customer support ticket
   - Reads: `ticket_content`, `customer_id`, `ticket_id`
   - Writes: `parsed_data`, `category_hint`

2. **categorize-issue** (llm_generate)
   - Classify the ticket type and assign priority
   - Reads: `parsed_data`, `category_hint`
   - Writes: `category`, `priority`, `confidence`

3. **generate-response** (llm_generate)
   - Create a helpful response for the customer
   - Reads: `parsed_data`, `category`, `priority`
   - Writes: `response_text`, `suggested_actions`

### Edges (2 total)

- `parse-ticket` → `categorize-issue` (condition: on_success)
- `categorize-issue` → `generate-response` (condition: on_success)

## Goal Criteria

### Success Criteria

**Correctly extract key information from ticket content** (weight 0.25)
- Metric: extraction_accuracy
- Target: 95%

**Correctly classify ticket type and priority** (weight 0.3)
- Metric: classification_accuracy
- Target: 90%

**Provide helpful, professional responses** (weight 0.3)
- Metric: customer_satisfaction
- Target: 85%

**Process tickets quickly** (weight 0.15)
- Metric: processing_time
- Target: <30s

### Constraints

**Must not expose sensitive customer data in logs or outputs** (security)
- Category: data_privacy

**Escalate to human when confidence below 70%** (quality)
- Category: accuracy

**Complete processing within 60 seconds** (performance)
- Category: latency

## Required Tools

No external tools required - this agent uses only LLM nodes.

## Installation & Setup

### 1. Framework Setup

Install the Hive framework (one-time):

```bash
cd /path/to/hive
./scripts/setup-python.sh
```

This installs:
- `framework` - Core agent runtime
- `aden_tools` - MCP tools package
- All dependencies

See [ENVIRONMENT_SETUP.md](../../ENVIRONMENT_SETUP.md) for detailed setup instructions.

### 2. Verify Installation

```bash
# From hive/ directory
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

**Expected output**: Validation passes with possible warnings about missing API keys (acceptable for mock mode).

## Usage

All commands must be run from the project root (`/path/to/hive/`) with `PYTHONPATH=core:exports`.

### Validate Agent Structure

```bash
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

Checks:
- Agent.json is valid
- All nodes are properly configured
- Edges connect correctly
- Required tools are available

### Display Agent Information

```bash
PYTHONPATH=core:exports python -m support_ticket_agent info
```

Shows:
- Node count and details
- Edge connections
- Goal and success criteria
- Constraints
- Required inputs/outputs

### Run Agent (Mock Mode)

**Recommended for testing** - No API key required:

```bash
PYTHONPATH=core:exports python -m support_ticket_agent run --mock --input '{
  "ticket_content": "My login is broken. Error 401.",
  "customer_id": "CUST-123",
  "ticket_id": "TKT-456"
}'
```

Mock mode uses simulated LLM responses, perfect for:
- Verifying installation
- Testing agent structure
- Development and debugging

### Run Agent (Real LLM)

Requires an API key for your chosen LLM provider:

```bash
# Set API key (choose one based on model)
export CEREBRAS_API_KEY="your-key-here"  # For cerebras models (default)
export ANTHROPIC_API_KEY="your-key-here"  # For Claude models
export OPENAI_API_KEY="your-key-here"     # For GPT models

# Run with default model (cerebras/zai-glm-4.7)
PYTHONPATH=core:exports python -m support_ticket_agent run --input '{
  "ticket_content": "I cannot access my account. Getting timeout errors.",
  "customer_id": "CUST-456",
  "ticket_id": "TKT-789"
}'

# Run with custom model
PYTHONPATH=core:exports python -m support_ticket_agent run \
  --model "claude-sonnet-4-20250514" \
  --input '{"ticket_content": "...", "customer_id": "...", "ticket_id": "..."}'
```

### Run Demo

Quick test with pre-configured example:

```bash
# Mock mode (no API key needed)
PYTHONPATH=core:exports python -m support_ticket_agent demo --mock

# Real LLM mode
export CEREBRAS_API_KEY="your-key"
PYTHONPATH=core:exports python -m support_ticket_agent demo
```

## Input Schema

The agent's entry node `parse-ticket` requires:

- `ticket_content` (required): The full text of the customer's support ticket
- `customer_id` (required): Unique customer identifier (e.g., "CUST-12345")
- `ticket_id` (required): Unique ticket identifier (e.g., "TKT-98765")

**Example**:
```json
{
  "ticket_content": "My login is broken. I keep getting 'Error 401: Unauthorized' when I try to access my account. This started after yesterday's maintenance.",
  "customer_id": "CUST-12345",
  "ticket_id": "TKT-98765"
}
```

## Output Schema

Terminal node: `generate-response`

**Final output includes**:
- `response_text`: Generated customer response
- `suggested_actions`: Array of recommended actions
- `category`: Ticket classification (login, billing, technical, etc.)
- `priority`: Assigned priority (low, medium, high, critical)
- `confidence`: Classification confidence (0.0-1.0)
- `parsed_data`: Extracted ticket information

## Example I/O

### Input
```json
{
  "ticket_content": "I can't log in. Error 401 keeps appearing!",
  "customer_id": "CUST-789",
  "ticket_id": "TKT-123"
}
```

### Output (Mock Mode)
```json
{
  "parsed_data": {
    "subject": "Login Issue - Error 401",
    "issue_description": "Unable to authenticate",
    "sentiment": "negative",
    "urgency_level": "high"
  },
  "category": "login",
  "priority": "high",
  "confidence": 0.95,
  "response_text": "We apologize for the login issue. Our team will investigate the 401 error.",
  "suggested_actions": ["reset_password", "check_session", "escalate_if_persistent"]
}
```

## Programmatic Usage

```python
from framework.runner import AgentRunner

# Load agent
runner = AgentRunner.load("exports/support_ticket_agent", mock_mode=True)

# Run with input
result = await runner.run({
    "ticket_content": "My login is broken. Error 401.",
    "customer_id": "CUST-123",
    "ticket_id": "TKT-456"
})

# Access results
print(result.output)
print(result.status)
print(result.path)  # ['parse-ticket', 'categorize-issue', 'generate-response']
```

## LLM Provider Configuration

The agent defaults to **Cerebras** (`cerebras/zai-glm-4.7`) for cost-effective inference.

### Supported Providers

Via LiteLLM, the agent supports 100+ models including:

| Provider | Model Example | API Key |
|----------|---------------|---------|
| Cerebras | `cerebras/zai-glm-4.7` | `CEREBRAS_API_KEY` |
| OpenAI | `gpt-4o-mini`, `gpt-4o` | `OPENAI_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| Google | `gemini/gemini-pro` | `GOOGLE_API_KEY` |
| Local (Ollama) | `ollama/llama3` | None (runs locally) |

### Changing the Model

```bash
# Via CLI flag
python -m support_ticket_agent run --model "gpt-4o-mini" --input '{...}'

# Programmatically
runner = AgentRunner.load("exports/support_ticket_agent", model="claude-sonnet-4-20250514")
```

## Troubleshooting

### "No module named 'framework'"

**Cause**: Not running from project root or PYTHONPATH not set.

**Solution**:
```bash
cd /path/to/hive
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

### "API key not set" warnings

**Expected** if you haven't configured an LLM provider. Use `--mock` to run without API keys:

```bash
PYTHONPATH=core:exports python -m support_ticket_agent run --mock --input '{...}'
```

### Agent validation fails

Check that the framework is properly installed:
```bash
./scripts/setup-python.sh
```

## Version History

- **1.0.0** (2026-01-29): Initial release
  - 3 nodes, 2 edges
  - Goal: Process Customer Support Tickets
  - Linear execution flow
  - Mock mode support
  - Complete CLI interface
