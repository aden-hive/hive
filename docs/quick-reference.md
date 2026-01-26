# Quick Reference Guide

A quick lookup guide for common tasks and patterns in the Aden Hive Framework.

## Setup & Installation

### Quick Setup
```bash
git clone https://github.com/adenhq/hive.git
cd hive
./scripts/setup-python.sh
python -c "import framework; print('✓ Ready')"
```

### Development Helper Commands
```bash
# Windows
dev-help.bat setup      # Full setup
dev-help.bat test       # Run tests
dev-help.bat validate   # Check agents

# macOS/Linux
./dev-help.sh setup
./dev-help.sh test
./dev-help.sh validate
```

---

## Building Agents

### Option 1: Using Claude Code (Recommended)
```bash
./quickstart.sh
claude> /building-agents
```

### Option 2: Manual Creation
```bash
mkdir -p exports/my_agent
# Create agent.json, agent.py, tools.py
```

### Option 3: Programmatic
```python
from framework import AgentRunner, Runtime

runtime = Runtime("my_agent")
runner = AgentRunner("exports/my_agent")
result = await runner.run({"input": "test"})
```

---

## Running Agents

### Basic Execution
```bash
PYTHONPATH=core:exports python -m my_agent run --input '{...}'
```

### Mock Mode (No API Calls)
```bash
PYTHONPATH=core:exports python -m my_agent run --mock --input '{...}'
```

### Verbose Output
```bash
PYTHONPATH=core:exports python -m my_agent run \
  --input '{...}' \
  --verbose
```

### With Environment Variables
```bash
export ANTHROPIC_API_KEY="your-key"
PYTHONPATH=core:exports python -m my_agent run --input '{...}'
```

---

## Testing

### Run All Tests
```bash
dev-help.sh test                    # Unix
dev-help.bat test                   # Windows
```

### Run Specific Test File
```bash
PYTHONPATH=core:exports python -m pytest core/tests/test_builder.py -v
```

### Run with Coverage
```bash
dev-help.sh test:coverage
# Results in htmlcov/index.html
```

### Test Specific Agent
```bash
dev-help.sh validate:agent my_agent
```

---

## Code Structure

### Agent Directory Layout
```
exports/my_agent/
├── agent.json          # Configuration
├── agent.py            # Main agent logic
├── tools.py            # Custom tools
├── nodes.py            # Node definitions
├── __init__.py
├── README.md
└── tests/
    ├── test_constraints.py
    └── test_success_criteria.py
```

### Agent Configuration (agent.json)
```json
{
  "name": "my_agent",
  "version": "1.0.0",
  "description": "What this agent does",
  "goal": {
    "id": "goal-1",
    "name": "Agent Goal",
    "description": "Goal description",
    "success_criteria": [],
    "constraints": []
  },
  "graph": {
    "nodes": [],
    "edges": []
  },
  "tools": []
}
```

---

## Common Runtime Patterns

### Decision with Tracking
```python
runtime.set_node("decision_node")
decision = runtime.decide(
    intent="What are we trying to do?",
    options=[
        {"id": "opt1", "description": "Option 1"},
        {"id": "opt2", "description": "Option 2"}
    ],
    chosen="opt1",
    reasoning="Because..."
)
runtime.record_outcome(decision, success=True, result={...})
```

### Error Handling
```python
try:
    result = await runner.run(input_data)
    if result.success:
        print(result.output)
    else:
        print(f"Agent error: {result.error}")
except Exception as e:
    print(f"Execution error: {e}")
```

### Memory Operations
```python
from framework.memory import ShortTermMemory, LongTermMemory

# Short-term
stm = ShortTermMemory()
stm.add("key", "value")
value = stm.get("key")

# Long-term
ltm = LongTermMemory(db_path="memory.db")
ltm.store("pattern", {"data": "..."})
```

---

## LLM Provider Selection

### Anthropic (Best Reasoning)
```python
from framework.llm import AnthropicProvider

provider = AnthropicProvider()
response = await provider.generate("prompt", max_tokens=1000)
```

### OpenAI (Cost-Effective)
```python
from framework.llm import OpenAIProvider

provider = OpenAIProvider(model="gpt-4o-mini")
response = await provider.generate("prompt")
```

### Google Gemini (Fast)
```python
from framework.llm import LiteLLMProvider

provider = LiteLLMProvider(model="gemini-2.0-flash")
response = await provider.generate("prompt")
```

### Any Provider (LiteLLM)
```python
from framework.llm import LiteLLMProvider

# Cerebras (free)
provider = LiteLLMProvider(model="cerebras/llama-3.3-70b")

# Mistral
provider = LiteLLMProvider(model="mistral/mistral-large")

# Groq
provider = LiteLLMProvider(model="groq/mixtral-8x7b-32768")
```

---

## Tools & Integrations

### Using Built-in MCP Tools
```python
# In your agent's tools.py
from aden_tools import (
    WebSearchTool,
    WebScrapeTool,
    FileReadTool,
    ExecuteCommandTool
)

async def search_web(query):
    tool = WebSearchTool()
    return await tool.execute(query=query)
```

### Web Search
```python
from aden_tools import WebSearchTool

tool = WebSearchTool(api_key="brave-api-key")
results = await tool.execute(query="python asyncio")
```

### File Operations
```python
from aden_tools import FileReadTool, FileWriteTool

read_tool = FileReadTool()
write_tool = FileWriteTool()

content = await read_tool.execute(path="file.txt")
await write_tool.execute(path="output.txt", content="data")
```

### HTTP Requests
```python
from aden_tools import HttpRequestTool

tool = HttpRequestTool()
response = await tool.execute(
    method="GET",
    url="https://api.example.com/data"
)
```

---

## Debugging

### Enable Verbose Logging
```bash
PYTHONPATH=core:exports python -m my_agent run \
  --input '{...}' \
  --verbose \
  --log-level debug
```

### Print Decision Data
```python
# During agent execution
runtime.set_node("debug")
print(f"Node: {runtime.current_node}")
print(f"Run: {runtime.current_run_id}")
```

### Check Agent Validation
```bash
PYTHONPATH=core:exports python -m my_agent validate
PYTHONPATH=core:exports python -m my_agent info
```

---

## API Keys & Environment

### Set API Keys
```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Brave Search
export BRAVE_SEARCH_API_KEY="..."

# Google
export GOOGLE_API_KEY="..."
```

### Using .env File
```bash
# Create .env in project root
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Load it
set -o allexport
source .env
set +o allexport
```

### Check API Key
```bash
echo $ANTHROPIC_API_KEY
# Shows first few characters
```

---

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: framework` | `pip install -e core/` |
| `ModuleNotFoundError: aden_tools` | `pip install -e tools/` |
| `API key required` | Set `ANTHROPIC_API_KEY` env var |
| `No module named 'my_agent'` | Ensure agent in `exports/my_agent/` |
| `Event loop is closed` | Use `@pytest.mark.asyncio` decorator |
| `pytest not found` | `pip install pytest pytest-asyncio` |

---

## Project Paths

```
hive/
├── core/              Framework code
├── tools/             MCP tools package
├── exports/           User-created agents
├── .claude/           Claude Code skills
├── docs/              Documentation
├── scripts/           Setup and utility scripts
└── tests/             Unit tests
```

---

## Useful Commands

### Setup
```bash
./scripts/setup-python.sh
cd core && python setup_mcp.py && cd ..
python -c "import framework; import aden_tools; print('OK')"
```

### Development
```bash
dev-help.sh setup          # Full setup
dev-help.sh test           # Run tests
dev-help.sh lint           # Check code
dev-help.sh format         # Format code
dev-help.sh clean          # Clean cache
```

### Validation
```bash
dev-help.sh validate       # Check all agents
dev-help.sh validate:agent my_agent
```

### Execution
```bash
dev-help.sh run:agent my_agent
PYTHONPATH=core:exports python -m my_agent run --mock --input '{}'
```

---

## Resources

- **Docs**: [docs.adenhq.com](https://docs.adenhq.com/)
- **GitHub**: [github.com/adenhq/hive](https://github.com/adenhq/hive)
- **Discord**: [discord.gg/aden](https://discord.com/invite/MXE49hrKDk)
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)

---

## Advanced Topics

### Custom Nodes
```python
async def custom_node(input_data, runtime):
    runtime.set_node("custom")
    # Your logic here
    runtime.record_outcome(success=True, result={})
    return output_data
```

### Provider-Agnostic Agents
```python
# Define provider once, reuse everywhere
def get_llm_provider():
    from framework.llm import LiteLLMProvider
    return LiteLLMProvider(model=os.getenv("LLM_MODEL", "gpt-4o-mini"))
```

### Performance Monitoring
```bash
PYTHONPATH=core:exports python -m my_agent run \
  --input '{...}' \
  --profile \
  --metrics
```

---

## Getting Help

1. **Check Docs**: [docs/](../docs/)
2. **Troubleshooting**: [docs/troubleshooting.md](troubleshooting.md)
3. **API Reference**: [docs/api.md](api.md)
4. **GitHub Issues**: Report bugs or ask questions
5. **Discord**: Join community discussions

---

**Last Updated**: January 26, 2026
