# Your First Successful Agent

This walkthrough guides you through building, validating, and running your first successful agent using the Hive Agent Framework. By the end, you'll have a working **Sentiment Analysis Agent** that processes text input and returns sentiment classifications.

## What You'll Build

A simple sentiment analysis agent that:
- Accepts text input (e.g., product reviews, customer feedback)
- Analyzes the sentiment using an LLM
- Returns a structured response with sentiment classification and confidence score

## Prerequisites

Before starting, ensure you have:
- **Python version supported by Hive** (see [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md))
- **Hive framework** set up (see [Getting Started](getting-started.md))
- **API key** for your LLM provider (Anthropic, OpenAI, etc.)

> [!TIP]
> If you haven't set up Hive yet, run `./quickstart.sh` from the repository root to install all dependencies.

## Step 1: Create the Agent Directory

First, create a directory for your agent. In this walkthrough, we place it under the `exports/` folder:

```bash
# Navigate to the Hive repository root
cd hive

# Create the agent directory
mkdir -p exports/sentiment_agent
cd exports/sentiment_agent
```

> [!NOTE]
> In this walkthrough, we place the agent under `exports/` to keep user-created agents separate from the framework code. Your setup may differ.

## Step 2: Define the Agent Configuration

Create an agent configuration file (for example, `agent.json`, depending on your setup) that defines your agent's goal, nodes, and execution flow.

The following example shows a minimal single-node agent configuration for illustration purposes:

```json
{
  "goal": {
    "goal_id": "sentiment_analysis",
    "name": "Sentiment Analysis Agent",
    "description": "Analyze text input and classify sentiment as positive, negative, or neutral",
    "success_criteria": "Returns sentiment classification with confidence score"
  },
  "nodes": [
    {
      "node_id": "analyze_sentiment",
      "name": "Analyze Sentiment",
      "node_type": "llm_generate",
      "system_prompt": "You are a sentiment analysis expert. Analyze the provided text and classify its sentiment as positive, negative, or neutral. Provide a confidence score between 0 and 1.",
      "input_keys": ["text"],
      "output_keys": ["sentiment", "confidence", "reasoning"]
    }
  ],
  "edges": [
    {
      "edge_id": "start_to_analyze",
      "source": "START",
      "target": "analyze_sentiment",
      "condition": "on_success"
    },
    {
      "edge_id": "analyze_to_end",
      "source": "analyze_sentiment",
      "target": "END",
      "condition": "on_success"
    }
  ]
}
```

### Understanding the Configuration

- **goal**: Defines what your agent is designed to accomplish
- **nodes**: Individual units of work (in this case, one LLM call)
  - `node_type: "llm_generate"` - Makes an LLM call with the system prompt
  - `input_keys` - Data the node expects to receive
  - `output_keys` - Data the node will produce
- **edges**: Define the execution flow between nodes
  - `START` → `analyze_sentiment` → `END`

## Step 3: Create the Agent Package Files

Create the required Python package files:

```bash
# Create __init__.py
touch __init__.py

# Create __main__.py for CLI support
cat > __main__.py << 'EOF'
from framework.runner import AgentRunner
import sys

if __name__ == "__main__":
    runner = AgentRunner.from_file("exports/sentiment_agent/agent.json")
    runner.run_cli(sys.argv[1:])
EOF
```

## Step 4: Validate the Agent

Before running the agent, validate that the configuration is correct.

Ensure your agent package is discoverable on `PYTHONPATH` before running these commands.

> [!NOTE]
> The exact execution command may vary depending on your setup. The example below illustrates a typical workflow.

```bash
# From the hive repository root
PYTHONPATH=core:exports python -m sentiment_agent validate
```

**Expected output:**
```
✓ Agent configuration is valid
✓ All nodes are properly defined
✓ Graph structure is valid (START → analyze_sentiment → END)
✓ No circular dependencies detected
```

> [!IMPORTANT]
> If validation fails, check that your `agent.json` syntax is correct and all required fields are present.

## Step 5: Run Your First Agent

Now execute the agent with sample input:

> [!NOTE]
> The exact execution command may vary depending on your setup. The example below illustrates a typical workflow.

```bash
PYTHONPATH=core:exports python -m sentiment_agent run --input '{
  "text": "This product exceeded my expectations! The quality is outstanding and delivery was fast."
}'
```

### Expected Success Output

```json
{
  "sentiment": "positive",
  "confidence": 0.95,
  "reasoning": "The text contains strong positive indicators: 'exceeded expectations', 'outstanding quality', and 'fast delivery'. No negative sentiment detected.",
  "status": "success",
  "execution_time_ms": 1247
}
```

> [!TIP]
> **Success Indicators:**
> - ✅ `"status": "success"` - Agent completed without errors
> - ✅ All `output_keys` are present in the response
> - ✅ Sentiment classification matches the input text tone

## Step 6: Test with Different Inputs

Try running the agent with various sentiment types:

**Negative sentiment:**
```bash
PYTHONPATH=core:exports python -m sentiment_agent run --input '{
  "text": "Terrible experience. The product broke after one day and customer service was unhelpful."
}'
```

**Neutral sentiment:**
```bash
PYTHONPATH=core:exports python -m sentiment_agent run --input '{
  "text": "The product arrived on time. It works as described in the specifications."
}'
```

## Step 7: View Agent Information

Get detailed information about your agent:

```bash
PYTHONPATH=core:exports python -m sentiment_agent info
```

This displays:
- Agent goal and description
- Node definitions and types
- Execution graph structure
- Input/output schema

## Common Pitfalls and Solutions

### Issue: `ModuleNotFoundError: No module named 'framework'`

**Solution:**
```bash
cd core
pip install -e .
```

### Issue: `API key not found`

**Solution:**
```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"

# Or create a .env file in the repository root
echo 'ANTHROPIC_API_KEY=your-key-here' > .env
```

### Issue: Agent returns empty or malformed output

**Solution:**
- Verify your `output_keys` match what the LLM is instructed to return in the `system_prompt`
- Check that the input JSON is properly formatted
- Run with `--verbose` flag for detailed execution logs

## Next Steps

Now that you have a working agent, you can:

1. **Add Custom Tools**: Create a `tools.py` file with custom Python functions (see [DEVELOPER.md](../DEVELOPER.md#adding-custom-tools-to-an-agent))
2. **Add More Nodes**: Build multi-step workflows with routing logic
3. **Integrate MCP Servers**: Connect external tools like web search or file operations
4. **Write Tests**: Create test cases to validate agent behavior (see [Testing Agents](../DEVELOPER.md#testing-agents))
5. **Use Mock Mode**: Test without LLM calls using `--mock` flag

## Additional Resources

- **[Getting Started Guide](getting-started.md)** - Initial setup and installation
- **[Developer Guide](../DEVELOPER.md)** - Comprehensive development documentation
- **[Environment Setup](../ENVIRONMENT_SETUP.md)** - Detailed Python environment configuration
- **[Contributing Guide](../CONTRIBUTING.md)** - How to contribute to Hive

## Getting Help

- **Documentation**: Browse the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)

---

**Congratulations!** 🎉 You've successfully built, validated, and run your first Hive agent. You now understand the core concepts of agent configuration, node definitions, and execution flow.
