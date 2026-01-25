# Hello Agent 👋

A minimal example agent demonstrating the core concepts of the Aden Hive Framework.

## Overview

This agent is designed as a **learning resource** for new contributors. It shows:

- ✅ How an agent is **defined** (via `agent.json`)
- ✅ How an agent is **executed** (via CLI or programmatically)
- ✅ What **input/output** looks like

## Agent Structure

```
hello_agent/
├── agent.json      # Agent definition (goal, nodes, edges)
├── __init__.py     # Package initialization
├── __main__.py     # CLI entry point
└── README.md       # This file
```

## Quick Start

### 1. Setup (if not already done)

```bash
cd hive
./scripts/setup-python.sh
```

### 2. Validate the Agent

```bash
PYTHONPATH=core:exports python -m hello_agent validate
```

Expected output:
```
✓ Agent 'Hello Agent' is valid
  - 1 node(s)
  - 2 edge(s)
  - Entry: greeter
```

### 3. Show Agent Info

```bash
PYTHONPATH=core:exports python -m hello_agent info
```

### 4. Run the Agent

```bash
# Set your API key (choose one)
export ANTHROPIC_API_KEY="your-key"
# or
export OPENAI_API_KEY="your-key"

# Run with input
PYTHONPATH=core:exports python -m hello_agent run --input '{"user_name": "Alice"}'
```

Expected output:
```
🚀 Starting execution: Hello Agent
   Goal: A minimal example agent that greets the user...
   Entry node: greeter

▶ Step 1: Greeting Generator (llm_generate)
   ✓ Success
   📝 Summary: Generated a warm greeting for Alice

✓ Execution complete!
   Output: {"greeting": "Hello Alice! Welcome..."}
```

### 5. Run in Mock Mode (No API Key Required)

```bash
PYTHONPATH=core:exports python -m hello_agent run --mock --input '{"user_name": "Bob"}'
```

## How It Works

### Goal Definition

The agent has a clear **goal** with success criteria:

```json
{
  "goal": {
    "name": "Hello Agent",
    "description": "A minimal example agent that greets the user...",
    "success_criteria": [
      "Generate a personalized greeting for the user",
      "Include the user's name in the response"
    ]
  }
}
```

### Node Definition

A single **LLM node** that generates the greeting:

```json
{
  "id": "greeter",
  "name": "Greeting Generator",
  "node_type": "llm_generate",
  "system_prompt": "You are a friendly assistant...",
  "input_keys": ["user_name"],
  "output_keys": ["greeting"]
}
```

### Edge Connections

Simple linear flow:

```
START → greeter → END
```

## Programmatic Usage

```python
import asyncio
from framework.runner import AgentRunner

async def main():
    # Load the agent
    runner = AgentRunner.load("exports/hello_agent")
    
    # Run with input
    result = await runner.run({"user_name": "Alice"})
    
    print(f"Greeting: {result.get('greeting')}")

asyncio.run(main())
```

## Next Steps

After understanding this example, explore:

1. **Multi-node agents** - Add more nodes with different types
2. **Router nodes** - Conditional branching based on input
3. **Tool-using agents** - Integrate MCP tools for external capabilities
4. **Human-in-the-loop** - Add intervention points for human approval

See the [Developer Guide](../../DEVELOPER.md) for more advanced patterns.

## Contributing

This example is maintained as part of the Aden Hive Framework. 
If you find issues or have suggestions, please open an issue or PR!

---

*Happy building! 🐝*
