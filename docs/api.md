# Framework API Documentation

This document provides a comprehensive reference for the key APIs in the Aden Hive Framework.

## Table of Contents

1. [Runtime API](#runtime-api)
2. [Agent Runner API](#agent-runner-api)
3. [Graph Executor API](#graph-executor-api)
4. [LLM Provider API](#llm-provider-api)
5. [Memory API](#memory-api)
6. [Tools API](#tools-api)

---

## Runtime API

The `Runtime` class is the core component that manages agent execution, decision tracking, and outcome recording.

### Class: Runtime

```python
from framework import Runtime

runtime = Runtime(session_name="my_session")
```

#### Methods

##### `start_run(goal_id: str, goal_description: str) -> str`

Starts a new agent run.

**Parameters:**
- `goal_id` (str): Unique identifier for the goal
- `goal_description` (str): Human-readable description of the goal

**Returns:**
- `str`: The unique run ID for this execution

**Example:**
```python
run_id = runtime.start_run(
    goal_id="email-processor",
    goal_description="Process and categorize incoming emails"
)
```

---

##### `set_node(node_name: str) -> None`

Sets the current node being executed.

**Parameters:**
- `node_name` (str): Name of the node

**Example:**
```python
runtime.set_node("email-parser")
```

---

##### `decide(intent: str, options: List[Dict], chosen: str, reasoning: str = "") -> str`

Records a decision point in the agent execution.

**Parameters:**
- `intent` (str): What the agent is trying to accomplish
- `options` (List[Dict]): Available choices with format:
  ```python
  [
      {"id": "option1", "description": "First option", "pros": ["pro1"]},
      {"id": "option2", "description": "Second option", "pros": ["pro2"]}
  ]
  ```
- `chosen` (str): ID of the chosen option
- `reasoning` (str, optional): Why this option was chosen

**Returns:**
- `str`: Decision ID for tracking outcomes

**Example:**
```python
decision_id = runtime.decide(
    intent="Determine email priority",
    options=[
        {"id": "high", "description": "High priority", "pros": ["urgent", "from CEO"]},
        {"id": "low", "description": "Low priority", "pros": ["spam", "newsletter"]}
    ],
    chosen="high",
    reasoning="Email from CEO with urgent flag"
)
```

---

##### `record_outcome(decision_id: str, success: bool, result: Any = None, error: str = None, tokens_used: int = 0) -> None`

Records the outcome of a decision.

**Parameters:**
- `decision_id` (str): ID from `decide()`
- `success` (bool): Whether the decision led to success
- `result` (Any, optional): Result data from the operation
- `error` (str, optional): Error message if operation failed
- `tokens_used` (int, optional): LLM tokens consumed

**Example:**
```python
runtime.record_outcome(
    decision_id=decision_id,
    success=True,
    result={"priority": "high", "category": "urgent"},
    tokens_used=150
)
```

---

##### `end_run(success: bool, narrative: str = "") -> None`

Ends the current run.

**Parameters:**
- `success` (bool): Overall success of the run
- `narrative` (str, optional): Summary of what was accomplished

**Example:**
```python
runtime.end_run(
    success=True,
    narrative="Successfully processed 50 emails, categorized by priority"
)
```

---

### Class: BuilderQuery

Used by Builder LLM to analyze and improve agents based on run data.

#### Methods

##### `from_run_id(run_id: str) -> BuilderQuery`

Load query data from a specific run.

**Parameters:**
- `run_id` (str): ID of the run to analyze

**Returns:**
- `BuilderQuery`: Query object with run analysis

**Example:**
```python
query = BuilderQuery.from_run_id("run-123")
decisions = query.get_decisions()
```

---

## Agent Runner API

The `AgentRunner` class loads and executes agents.

### Class: AgentRunner

```python
from framework import AgentRunner

runner = AgentRunner(agent_path="exports/my_agent")
```

#### Methods

##### `__init__(agent_path: str, verbose: bool = False) -> None`

Initialize the agent runner.

**Parameters:**
- `agent_path` (str): Path to agent directory (e.g., 'exports/my_agent')
- `verbose` (bool, optional): Enable verbose logging

**Example:**
```python
runner = AgentRunner(
    agent_path="exports/email_processor",
    verbose=True
)
```

---

##### `validate() -> Tuple[bool, List[str]]`

Validate agent configuration and structure.

**Returns:**
- `Tuple[bool, List[str]]`: (is_valid, error_messages)

**Example:**
```python
is_valid, errors = runner.validate()
if not is_valid:
    for error in errors:
        print(f"Validation error: {error}")
```

---

##### `run(input_data: Dict, mock_mode: bool = False) -> ExecutionResult`

Execute the agent with given input.

**Parameters:**
- `input_data` (Dict): Input data for the agent
- `mock_mode` (bool, optional): Run without LLM calls

**Returns:**
- `ExecutionResult`: Execution result with:
  - `success` (bool): Whether execution succeeded
  - `output` (Dict): Output data from the agent
  - `error` (str): Error message if execution failed

**Example:**
```python
result = await runner.run(
    input_data={"email_text": "Hello..."},
    mock_mode=False
)

if result.success:
    print(f"Output: {result.output}")
else:
    print(f"Error: {result.error}")
```

---

## Graph Executor API

The `GraphExecutor` executes the node graph that makes up an agent.

### Class: GraphExecutor

```python
from framework.graph import GraphExecutor

executor = GraphExecutor(graph_config)
```

#### Methods

##### `execute(input_data: Dict, runtime: Runtime) -> ExecutionResult`

Execute the graph with given input.

**Parameters:**
- `input_data` (Dict): Input for the graph
- `runtime` (Runtime): Runtime instance for tracking

**Returns:**
- `ExecutionResult`: Result of graph execution

**Example:**
```python
result = await executor.execute(
    input_data={"query": "test"},
    runtime=runtime
)
```

---

## LLM Provider API

Different LLM providers can be used to power agents.

### Class: AnthropicProvider

```python
from framework.llm import AnthropicProvider

provider = AnthropicProvider(api_key="your-key")
```

#### Methods

##### `generate(prompt: str, max_tokens: int = 1024) -> str`

Generate text using the Anthropic API.

**Parameters:**
- `prompt` (str): Input prompt
- `max_tokens` (int, optional): Maximum response length

**Returns:**
- `str`: Generated text

**Example:**
```python
response = await provider.generate(
    prompt="Analyze this email: ...",
    max_tokens=500
)
```

---

### Class: OpenAIProvider

```python
from framework.llm import OpenAIProvider

provider = OpenAIProvider(api_key="your-key", model="gpt-4o")
```

#### Methods

##### `generate(prompt: str, max_tokens: int = 1024) -> str`

Generate text using OpenAI API.

**Parameters:**
- `prompt` (str): Input prompt
- `max_tokens` (int, optional): Maximum response length

**Returns:**
- `str`: Generated text

---

### Class: LiteLLMProvider

```python
from framework.llm import LiteLLMProvider

provider = LiteLLMProvider(model="gpt-4o-mini")
```

Support for 100+ LLM providers through LiteLLM.

#### Methods

##### `generate(prompt: str, max_tokens: int = 1024) -> str`

Generate text using any LiteLLM-supported provider.

**Parameters:**
- `prompt` (str): Input prompt
- `max_tokens` (int, optional): Maximum response length

**Returns:**
- `str`: Generated text

**Example:**
```python
# Use Gemini
provider = LiteLLMProvider(model="gemini-2.0-flash")
response = await provider.generate("Your prompt")

# Use Cerebras
provider = LiteLLMProvider(model="cerebras/llama-3.3-70b")
response = await provider.generate("Your prompt")
```

---

## Memory API

Memory systems for storing and retrieving agent knowledge.

### Class: ShortTermMemory

Stores recent decisions and outcomes (current session).

```python
from framework.memory import ShortTermMemory

memory = ShortTermMemory(max_size=20)
```

#### Methods

##### `add(key: str, value: Any) -> None`

Add item to short-term memory.

**Example:**
```python
memory.add("last_decision", "high_priority")
```

##### `get(key: str) -> Any`

Retrieve item from short-term memory.

**Example:**
```python
value = memory.get("last_decision")
```

##### `get_recent(count: int = 5) -> List[Tuple[str, Any]]`

Get recent items.

**Example:**
```python
recent = memory.get_recent(10)
```

---

### Class: LongTermMemory

Persistent memory for learning across sessions.

```python
from framework.memory import LongTermMemory

memory = LongTermMemory(
    db_path="agent_memory.db",
    retention_days=30
)
```

#### Methods

##### `store(key: str, value: Any, metadata: Dict = None) -> None`

Store item in long-term memory.

**Parameters:**
- `key` (str): Unique identifier
- `value` (Any): Data to store
- `metadata` (Dict, optional): Additional metadata

**Example:**
```python
memory.store(
    key="learned_pattern_email_spam",
    value={"keywords": ["free", "winner"], "confidence": 0.95},
    metadata={"source": "user_feedback"}
)
```

---

## Tools API

Framework for integrating tools and capabilities.

### Class: Tool

Base class for tool implementation.

```python
from framework.tools import Tool

class MyCustomTool(Tool):
    def __init__(self):
        self.name = "my_tool"
        self.description = "What this tool does"
    
    async def execute(self, **kwargs) -> Dict:
        # Implement tool logic
        return {"result": "..."}
```

---

### Available MCP Tools

The framework includes 19 pre-built MCP tools:

#### Web Tools
- `web_search`: Search the web using Brave Search
- `web_scrape`: Extract content from web pages
- `web_screenshot`: Take screenshots of websites

#### File System Tools
- `file_read`: Read file contents
- `file_write`: Write to files
- `file_delete`: Delete files
- `list_directory`: List directory contents
- `file_search`: Search for files

#### Data Processing Tools
- `json_parse`: Parse and validate JSON
- `csv_parse`: Parse CSV files
- `xml_parse`: Parse XML files
- `pdf_extract`: Extract text from PDFs

#### System Tools
- `execute_command`: Run shell commands
- `get_environment`: Get environment variables
- `get_system_info`: Get system information

#### Integration Tools
- `http_request`: Make HTTP requests
- `database_query`: Query databases
- `email_send`: Send emails

---

## Type Definitions

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    success: bool           # Whether execution succeeded
    output: Dict           # Output data from execution
    error: Optional[str]   # Error message if failed
    tokens_used: int = 0   # LLM tokens consumed
    duration: float = 0.0  # Execution time in seconds
```

---

### Goal

```python
@dataclass
class Goal:
    id: str                    # Goal identifier
    name: str                  # Human-readable name
    description: str           # Detailed description
    success_criteria: List[SuccessCriteria]  # How to measure success
    constraints: List[Constraint]  # Limitations and rules
    budget: Dict              # Token/cost budget (optional)
```

---

### Decision

```python
@dataclass
class Decision:
    id: str                    # Decision identifier
    node: str                  # Node name
    intent: str               # What agent was trying to accomplish
    options: List[Dict]       # Available choices
    chosen: str               # ID of chosen option
    reasoning: str            # Why this option was chosen
    outcome: Optional[Outcome]  # Result of this decision
```

---

## Examples

### Example 1: Simple Agent with Runtime Tracking

```python
from framework import Runtime, AgentRunner

# Create runtime
runtime = Runtime(session_name="email_agent")

# Start run
run_id = runtime.start_run(
    goal_id="process-emails",
    goal_description="Process incoming emails"
)

# Execute node
runtime.set_node("parser")
decision = runtime.decide(
    intent="Determine email type",
    options=[
        {"id": "spam", "description": "Spam"},
        {"id": "important", "description": "Important"}
    ],
    chosen="important",
    reasoning="From known contact"
)

# Record outcome
runtime.record_outcome(
    decision_id=decision,
    success=True,
    result={"type": "important"},
    tokens_used=100
)

# End run
runtime.end_run(success=True)

# Analyze with Builder
query = BuilderQuery.from_run_id(run_id)
```

---

### Example 2: Running an Agent

```python
from framework import AgentRunner

async def main():
    runner = AgentRunner("exports/my_agent")
    
    # Validate
    is_valid, errors = runner.validate()
    if not is_valid:
        print("Validation errors:", errors)
        return
    
    # Run
    result = await runner.run({
        "input": "Your input here"
    })
    
    if result.success:
        print("Output:", result.output)
        print("Tokens used:", result.tokens_used)
    else:
        print("Error:", result.error)

asyncio.run(main())
```

---

### Example 3: Using Different LLM Providers

```python
from framework.llm import (
    AnthropicProvider,
    OpenAIProvider,
    LiteLLMProvider
)

# Anthropic
provider = AnthropicProvider(api_key="sk-ant-...")
response = await provider.generate("Prompt here")

# OpenAI
provider = OpenAIProvider(api_key="sk-...", model="gpt-4o")
response = await provider.generate("Prompt here")

# LiteLLM (any provider)
provider = LiteLLMProvider(model="gemini-2.0-flash")
response = await provider.generate("Prompt here")
```

---

## Best Practices

1. **Always Validate Agents**: Call `validate()` before running
2. **Use Mock Mode for Testing**: Set `mock_mode=True` to test logic without API calls
3. **Track Decisions**: Use `Runtime.decide()` to capture decision points for analysis
4. **Handle Async Properly**: All `run()` methods are async, use `await`
5. **Monitor Tokens**: Track token usage for cost management
6. **Use Appropriate Providers**: Choose providers based on cost/quality tradeoff
7. **Implement Error Handling**: Always check `result.success` before accessing output
8. **Store Learning**: Use LongTermMemory to persist lessons across runs

---

## Additional Resources

- [Framework Architecture](architecture/README.md)
- [Developer Guide](../DEVELOPER.md)
- [Contributing Guidelines](../CONTRIBUTING.md)
- [Troubleshooting](troubleshooting.md)

---

**Last Updated**: January 26, 2026
