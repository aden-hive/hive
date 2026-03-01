# Hive Codebase Structure - Deep Dive

## 📚 Overview

**Hive** is a goal-driven agent framework that builds autonomous, self-improving AI agents without hardcoding workflows. The framework uses a **node-graph execution model** combined with a **decision-recording runtime** that enables AI agents (the "Builder") to analyze failures and improve themselves.

### Core Philosophy

- **Goal-Driven**: Define what the agent should achieve, not how
- **Self-Improving**: Captures all decisions and outcomes; Builder LLM analyzes failures and evolves the agent
- **Production-Ready**: Built-in human-in-the-loop, observability, and cost limits
- **Multi-Agent**: Support for agent coordination and handoffs

---

## 🏗️ High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hive Framework                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Builder    │  │   Runtime    │  │   Storage    │       │
│  │   (Query)    │  │   (Core)     │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         ▲                 ▲                   ▲              │
│         │                 │                   │              │
│  ┌─────────────────────────────────────────────────┐        │
│  │           Graph Executor                        │        │
│  │  (Orchestrates node execution following edges)  │        │
│  └──────────┬──────────────────────────────────────┘        │
│             │                                                │
│  ┌──────────┴──────────────────────────────┐               │
│  │          Node Types                     │               │
│  ├─────────────────────────────────────────┤               │
│  │ • LLMNode (llm_tool_use, llm_generate)  │               │
│  │ • RouterNode (routing logic)            │               │
│  │ • FunctionNode (Python functions)       │               │
│  │ • EventLoopNode (tool use loops)        │               │
│  │ • HumanInputNode (HITL)                 │               │
│  │ • WorkerNode (flexible execution)       │               │
│  └─────────────────────────────────────────┘               │
│                                                               │
│  ┌──────────────────────────────────────────┐              │
│  │      Key Components                      │              │
│  ├──────────────────────────────────────────┤              │
│  │ • Credentials (encrypted storage)        │              │
│  │ • LLM Provider (OpenAI, Anthropic, etc)  │              │
│  │ • MCP Server (Model Context Protocol)    │              │
│  │ • Tools (external integrations)          │              │
│  │ • Schemas (decision, run, checkpoints)   │              │
│  └──────────────────────────────────────────┘              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Directory Structure

### Root Level

```
hive/
├── core/                      # Main framework package
├── examples/                  # Example agents & recipes
├── docs/                      # Documentation & guides
├── tools/                     # MCP tools server
├── scripts/                   # Automation scripts
├── .mcp.json                  # MCP server configuration
├── package.json               # Node.js dependencies
├── pyproject.toml             # Python project root config
└── Makefile                   # Build commands
```

---

## 🔧 Core Framework (`core/`)

### Structure

```
core/
├── framework/                 # Main Python package
│   ├── __init__.py
│   ├── __main__.py           # Entry point for `python -m framework`
│   ├── cli.py                # Command-line interface
│   ├── pyproject.toml         # Package metadata & dependencies
│   │
│   ├── builder/              # Builder Query & Workflow components
│   ├── credentials/          # Credential management system
│   ├── graph/                # Graph execution engine
│   ├── llm/                  # LLM provider abstraction
│   ├── mcp/                  # Model Context Protocol server
│   ├── runtime/              # Runtime & decision logging
│   ├── schemas/              # Pydantic data models
│   ├── storage/              # Persistent storage backends
│   ├── testing/              # Testing utilities
│   ├── tui/                  # Terminal UI components
│   └── utils/                # Helper utilities
│
├── tests/                    # Comprehensive test suite
├── examples/                 # Code examples
│   ├── manual_agent.py       # Example: Manual agent control
│   ├── mcp_integration_example.py
│   └── mcp_servers.json
│
└── demos/                    # Live demo applications
    ├── event_loop_wss_demo.py
    ├── github_outreach_demo.py
    ├── handoff_demo.py
    └── org_demo.py
```

---

## 📦 Core Modules Deep Dive

### 1. **Graph Module** (`framework/graph/`)

**Purpose**: The execution engine that runs agent graphs

**Key Files**:

- **`node.py`** (1968 lines)
  - `NodeProtocol`: Abstract base for all nodes
  - `NodeSpec`: Configuration for a node
  - `NodeContext`: Execution context passed to nodes
  - `NodeResult`: Result returned from node execution
  - Node implementations:
    - `LLMNode`: Calls LLM with tools or generation
    - `RouterNode`: Intelligent routing based on LLM or functions
    - `FunctionNode`: Executes Python functions
    - `WorkerNode`: Flexible multi-action executor
- **`executor.py`** (large file)
  - `GraphExecutor`: Main orchestrator
    - Loads GraphSpec
    - Creates shared memory
    - Executes nodes in sequence
    - Follows edges (conditional routing)
    - Records all decisions
    - Handles retries and errors
    - Supports parallel execution
  - `ExecutionResult`: Contains final output and metadata

- **`edge.py`**
  - `EdgeSpec`: Connection between nodes
  - `EdgeCondition`: Routing logic
  - `GraphSpec`: Complete graph definition

- **`goal.py`**
  - `Goal`: What the agent is trying to achieve
  - `Constraint`: Limitations (budget, time, etc)
  - `SuccessCriterion`: How to measure success

- **`event_loop_node.py`**
  - `EventLoopNode`: Multi-turn tool use loop
  - `JudgeProtocol`: Determines when loop should exit
  - `LoopConfig`: Configuration for looping behavior

- **`worker_node.py`**
  - `WorkerNode`: Executes plan steps
  - Works with `PlanStep` and `ActionSpec`
  - Dispatches to tools, functions, or sub-graphs

- **`flexible_executor.py`**
  - `FlexibleGraphExecutor`: Worker-Judge pattern
  - Parallel execution with validation

- **`conversation.py`**
  - `ConversationStore`: Multi-turn conversation history
  - `Message`: Individual message in conversation
  - `NodeConversation`: Conversation for a specific node

- **`context_handoff.py`**
  - `ContextHandoff`: Pass context between agents
  - `HandoffContext`: Data structure for handoffs

- **Other utilities**:
  - `client_io.py`: Handle user input/output
  - `code_sandbox.py`: Safe Python code execution
  - `validator.py`: Output validation
  - `judge.py`: Determines execution completion
  - `checkpoint_config.py`: Resumable execution

### 2. **Runtime Module** (`framework/runtime/`)

**Purpose**: Records all decisions and outcomes for analysis

**Key Files**:

- **`core.py`**
  - `Runtime`: Main interface agents use

    ```python
    runtime = Runtime("/path/to/storage")

    run_id = runtime.start_run("goal_123", "Do something")
    decision_id = runtime.decide(
        intent="Choose action",
        options=[...],
        chosen="option_id",
        reasoning="..."
    )
    runtime.record_outcome(decision_id, success=True, result={...})
    runtime.end_run(success=True)
    ```

  - Methods record decisions → Stored in Run objects

- **`event_bus.py`**
  - Async event emission for streaming results
  - `emit_node_completed()`, `emit_execution_started()`, etc

- **`execution_stream.py`**
  - WebSocket streaming of execution progress
  - Real-time updates during graph execution

- **`runtime_logger.py`**
  - Hierarchical logging (L0: run, L1: goal, L2: node, L3: tool)
  - Tracks tokens, latency, errors

- **`shared_state.py`**
  - `SharedMemory`: Scoped memory between nodes
  - Tracks read/write permissions per node

### 3. **Builder Module** (`framework/builder/`)

**Purpose**: AI-driven improvement of agent graphs

**Key Files**:

- **`query.py`**
  - `BuilderQuery`: Analyze runs to find improvement opportunities
  - Methods:
    - `find_patterns()`: Detect failure patterns
    - `suggest_improvements()`: What to fix
    - `get_decision_trace()`: Understand what happened
    - `get_node_performance()`: Stats per node
    - `compare_runs()`: Diff between runs
  - Uses `PatternAnalysis` to identify:
    - Common failure modes
    - Problematic nodes
    - Success/failure rates

- **`workflow.py`**
  - `GraphBuilder`: Incremental graph building with HITL approval
  - Phases:
    1. Define goal
    2. Add nodes (one by one)
    3. Add edges
    4. Testing
    5. Final approval
  - Enforces validation at each step

### 4. **Schemas Module** (`framework/schemas/`)

**Purpose**: Pydantic models for all data structures

**Key Files**:

- **`run.py`**

  ```python
  Run:
    - id: str
    - goal_id: str
    - decisions: list[Decision]  # All decisions in this run
    - metrics: RunMetrics
    - status: RunStatus (running, completed, failed, stuck, cancelled)
    - problems: list[Problem]
    - narrative: str (summary)
  ```

- **`decision.py`**

  ```python
  Decision:
    - id: str
    - node_id: str
    - intent: str (what was being decided)
    - options: list[Option]
    - chosen: str (which option was picked)
    - reasoning: str (why)
    - outcome: Outcome | None
    - was_successful: bool
    - decision_type: DecisionType

  Outcome:
    - result: dict (what happened)
    - latency_ms: int
    - tokens_used: int
    - error: str | None
  ```

- **`checkpoint.py`**
  - `Checkpoint`: Save/restore execution state
  - For resumable execution

- **`session_state.py`**
  - `SessionState`: Agent session state tracking

### 5. **LLM Module** (`framework/llm/`)

**Purpose**: Abstract multiple LLM providers

**Files**:

- **`provider.py`**
  - `LLMProvider`: Abstract interface
  - `Tool`: Tool definition
  - Implementations via `litellm` (supports OpenAI, Anthropic, Google Gemini, etc)

### 6. **Storage Module** (`framework/storage/`)

**Purpose**: Persist runs, decisions, and checkpoints

**Key Files**:

- **`backend.py`**: `FileStorage` - Stores data as JSON files
- **`checkpoint_store.py`**: Save/restore execution checkpoints
- Directory structure:
  ```
  storage/
  ├── runs/               # One file per run
  ├── decisions/          # Decision logs
  └── checkpoints/        # Resumable state
  ```

### 7. **MCP Module** (`framework/mcp/`)

**Purpose**: Model Context Protocol server for Builder agents

**File**:

- **`agent_builder_server.py`**
  - Exposes framework tools via MCP
  - Allows Claude Code/Cursor to use Hive as a tool
  - Tools like:
    - `query_run()`: Get run details
    - `suggest_improvements()`: Get improvement ideas
    - `create_agent()`: Build new agent
    - `test_agent()`: Run tests

### 8. **Credentials Module** (`framework/credentials/`)

**Purpose**: Secure credential management

- Encrypted storage of API keys, tokens
- Vault integration support
- Per-node credential access

### 9. **Testing Module** (`framework/testing/`)

**Purpose**: Testing utilities for agents

- `TestCase`: Define test inputs and expected outputs
- `TestResult`: Track test execution
- Integration with pytest

### 10. **TUI Module** (`framework/tui/`)

**Purpose**: Terminal User Interface

- Live monitoring of agent execution
- Selection interfaces
- Real-time status updates

---

## 🔄 Execution Flow

### Step-by-Step: How an Agent Executes

```
1. CLI Command
   $ hive run exports/my-agent --input '{"key": "value"}'

2. Load Graph & Goal
   core/framework/cli.py → runner/cli.py
   - Load agent package from exports/
   - Parse GraphSpec and Goal

3. Initialize Runtime
   framework/runtime/core.py → Runtime()
   - Create storage directory
   - Start run ID generation

4. Create GraphExecutor
   framework/graph/executor.py → GraphExecutor()
   - Register all node implementations
   - Register tools
   - Initialize shared memory
   - Set up event bus for streaming

5. Execute Graph
   executor.execute(graph, goal, input_data)

   Loop:
   a) Find current node in graph
   b) Load NodeSpec (configuration)
   c) Build NodeContext (execution context)
   d) Call node.execute(ctx)

      Inside LLMNode.execute():
      - Build system prompt + messages
      - Call LLM (with tools if available)
      - Parse tool calls vs generation
      - Record decision to Runtime
      - Execute tools if requested
      - Build NodeResult

   e) Get NodeResult
      - success: bool
      - output: dict (for next node)
      - next_node: str | None (for routing)
      - error: str | None

   f) Find next node
      - Check if terminal node
      - Else: follow edge from result.next_node
      - Or: use EdgeCondition routing

   g) Update shared memory with output

   h) Record outcome to Runtime
      runtime.record_outcome(decision_id, success=result.success, ...)

   i) Repeat until terminal node reached

6. Return ExecutionResult
   - success: bool
   - output: dict
   - tokens_used: int
   - latency_ms: int
   - run_id: str (for analysis)

7. Store Run
   - All decisions persisted to storage/runs/{run_id}.json
   - Available for BuilderQuery analysis
```

### Key Data Structures

```python
# Graph Definition
GraphSpec:
  - id: str
  - name: str
  - description: str
  - nodes: dict[str, NodeSpec]     # Node configurations
  - edges: dict[str, EdgeSpec]     # Connections
  - initial_node: str
  - terminal_nodes: list[str]
  - tools: list[Tool]

# Single Execution
Run:
  - id: str
  - goal_id: str
  - status: RunStatus
  - decisions: list[Decision]      # Every decision in this run
  - metrics: RunMetrics
  - narrative: str

# Decision Detail
Decision:
  - intent: str (what was being decided)
  - options: list[Option] (alternatives considered)
  - chosen: str (what was picked)
  - reasoning: str (why)
  - outcome: Outcome (what actually happened)

# Analysis
PatternAnalysis:
  - common_failures: list[tuple[str, int]]  # Failure message → count
  - problematic_nodes: list[tuple[str, float]]  # node_id → failure_rate
  - decision_patterns: ...
```

---

## 🛠️ Key Subsystems

### 1. Decision Recording System

The foundation of self-improvement. Every node records:

```python
# 1. Before doing anything: Record the decision
decision_id = ctx.runtime.decide(
    intent="What are you trying to accomplish?",
    options=[
        {"id": "option1", "description": "..."},
        {"id": "option2", "description": "..."},
    ],
    chosen="option1",
    reasoning="Why did you pick option1?"
)

# 2. After action: Record the outcome
ctx.runtime.record_outcome(
    decision_id,
    success=True,  # Did it work?
    result={"output": "..."},
    summary="What happened?"
)
```

All decisions across all runs → Analyzed by BuilderQuery → Used to improve agent

### 2. Shared Memory System

Nodes communicate via scoped memory:

```python
# Node A output
output_data = {"result": 42, "metadata": {...}}

# Node B input (same data available)
input_data = {"result": 42, "metadata": {...}}

# Scoping enforced:
# NodeSpec.output_keys = ["result"]  # Only this goes to memory
# NodeSpec.input_keys = ["result"]   # Only this available to next node
```

### 3. Tool Use Loop (EventLoopNode)

Multi-turn LLM + tools until judge says stop:

```
1. LLM generates plan + first tool call
2. Execute tool
3. Judge: Should we continue?
   - Yes: Go to step 1 with new context
   - No: Stop, return final output
```

### 4. Human-in-the-Loop (HITL)

`HumanInputNode` pauses execution for human decision:

```
1. Agent reaches HITL node
2. System displays status + options
3. Human makes decision
4. Agent continues with human's choice
```

### 5. Parallel Execution

Multiple independent nodes can run simultaneously:

```python
executor = GraphExecutor(
    enable_parallel_execution=True,
    parallel_config=ParallelExecutionConfig(
        max_parallel_nodes=4,
        ...
    )
)
```

### 6. Checkpointing & Resumable Execution

Save execution state to resume later:

```python
checkpoint_config = CheckpointConfig(
    enabled=True,
    interval=5,  # Save every 5 decisions
    restore_from="checkpoint_id"
)

result = await executor.execute(
    graph=graph,
    ...,
    checkpoint_config=checkpoint_config
)
```

---

## 🧪 Testing Structure

```
core/tests/
├── test_builder.py              # Pattern analysis, workflow
├── test_graph_executor.py        # Graph execution
├── test_node_types.py            # Individual node types
├── test_event_loop_node.py       # Event loop behavior
├── test_executor_*.py            # Executor edge cases
├── test_concurrent_storage.py    # Storage safety
└── ... (50+ test files)
```

Each test:

- Creates temporary Runtime
- Builds GraphSpec + NodeSpecs
- Executes via GraphExecutor
- Validates results and side effects

---

## 📖 Examples & Documentation

### Examples (`examples/`)

```
examples/
├── README.md                     # Overview
├── recipes/                      # Reusable patterns
└── templates/                    # Starter agent templates
    ├── basic_agent/
    ├── research_agent/
    └── data_processing_agent/
```

### Documentation (`docs/`)

```
docs/
├── getting-started.md            # First steps
├── configuration.md              # Configuration options
├── developer-guide.md            # Building agents
├── environment-setup.md          # Dev setup
├── architecture/                 # Deep-dive docs
├── key_concepts/                 # Conceptual guides
├── articles/                     # Tutorials & guides
└── i18n/                         # Translations
```

---

## 🚀 Entry Points

### Command Line

```bash
# Run an agent
hive run exports/my-agent --input '{"key": "value"}'

# Get agent info
hive info exports/my-agent

# Validate agent
hive validate exports/my-agent

# List agents
hive list exports/

# Interactive shell
hive shell exports/my-agent

# Testing
hive test-run exports/my-agent --goal goal_123
hive test-list goal_123
```

### Programmatic API

```python
from framework.graph import GraphExecutor, GraphSpec, Goal
from framework.runtime import Runtime

runtime = Runtime("/path/to/storage")
executor = GraphExecutor(runtime=runtime, llm=llm_provider, tools=tools)

result = await executor.execute(
    graph=graph_spec,
    goal=goal,
    input_data={...}
)

# Later: Analyze
from framework.builder import BuilderQuery
query = BuilderQuery("/path/to/storage")
patterns = query.find_patterns("goal_123")
improvements = query.suggest_improvements("goal_123")
```

### MCP Server (for Builder)

```bash
# Runs in Claude Code, Cursor, etc.
uv run -m framework.mcp.agent_builder_server

# Exposes tools:
# - query_run(run_id)
# - find_patterns(goal_id)
# - suggest_improvements(goal_id)
# - create_node(node_spec)
# - validate_agent()
# - test_agent()
```

---

## 🔌 Extension Points

### Custom Nodes

```python
from framework.graph import NodeProtocol, NodeContext, NodeResult

class MyCustomNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Your logic here
        return NodeResult(success=True, output={...})

# Register with executor
executor.register_node("my-custom-id", MyCustomNode())
```

### Custom Tools

```python
from framework.llm.provider import Tool

tool = Tool(
    name="my_tool",
    description="What it does",
    input_schema={...},
    func=my_function
)

executor.tools.append(tool)
```

### Custom Storage

```python
from framework.storage.backend import StorageBackend

class MyStorage(StorageBackend):
    def save_run(self, run: Run) -> None: ...
    def load_run(self, run_id: str) -> Run | None: ...
    # ... other methods
```

---

## 📊 Key Metrics & Observability

### Runtime Logging

- **L0**: Run level (overall execution)
- **L1**: Goal level (goal pursuit)
- **L2**: Node level (per-node stats)
- **L3**: Tool level (tool call details)

Each level tracks:

- Tokens used
- Latency (ms)
- Success/failure
- Error messages

### Pattern Analysis

- **Success rate**: % of runs that succeeded
- **Common failures**: Failure messages and frequency
- **Problematic nodes**: Nodes with high failure rates
- **Decision patterns**: What types of decisions fail most

### Performance Metrics

```python
metrics = {
    "total_decisions": 42,
    "successful_decisions": 38,
    "failed_decisions": 4,
    "success_rate": 0.905,
    "avg_latency_ms": 1250,
    "total_tokens": 15000,
}
```

---

## 🔐 Security & Safety

### Credentials

- Encrypted storage of API keys
- Per-node credential access control
- Vault integration support

### Code Execution

- `CodeSandbox` for safe Python evaluation
- Restricted namespace (no `__import__`, `exec` by default)
- Configurable safety level

### Output Validation

- `OutputValidator`: Checks node outputs match spec
- `OutputCleaner`: Removes sensitive data
- Customizable cleansing rules

### Rate Limiting & Cost Control

- Per-node max retries
- Per-run token budget
- Parallel execution limits

---

## 🎯 Typical Workflow

### 1. **Build Phase** (Using Builder/Cursor)

```python
builder = GraphBuilder("my-agent")

# Define goal
builder.set_goal(Goal(
    id="classify_leads",
    description="Classify sales leads as hot/warm/cold"
))

# Add nodes
builder.add_node(NodeSpec(
    id="fetch_lead",
    node_type="function",
    function="fetch_lead_from_db"
))

builder.add_node(NodeSpec(
    id="classify",
    node_type="llm_tool_use",
    system_prompt="You are a lead classifier...",
    tools=["crm_lookup", "web_search"]
))

# Add edge
builder.add_edge(EdgeSpec(from_id="fetch_lead", to_id="classify"))

# Test & approve
builder.add_test(TestCase(input={...}, expected_output={...}))
builder.validate()
builder.approve("Looks good")

# Export
graph = builder.export()
```

### 2. **Run Phase** (In Production)

```bash
hive run exports/my-agent --input '{"lead_id": "123"}'
```

### 3. **Analyze Phase** (Builder Improvement Loop)

```python
query = BuilderQuery("/path/to/storage")

# After 100 runs:
patterns = query.find_patterns("classify_leads")

print(patterns.success_rate)  # 0.85
print(patterns.common_failures)  # [("timeout", 10), ("no_data", 5)]
print(patterns.problematic_nodes)  # [("classify", 0.3)]

improvements = query.suggest_improvements("classify_leads")
# → [{"type": "node_improvement", "target": "classify",
#      "reason": "30% failure rate", ...}]
```

### 4. **Improve Phase** (Using Builder/Cursor)

- Builder reads improvement suggestions
- Updates node prompts, tools, or logic
- Repeats to step 1

---

## 📝 Important Files to Know

### Must-Knows

| File                                 | Purpose                | Lines  |
| ------------------------------------ | ---------------------- | ------ |
| `core/framework/graph/executor.py`   | Main execution engine  | ~1000+ |
| `core/framework/graph/node.py`       | Node protocols & impls | ~1968  |
| `core/framework/runtime/core.py`     | Decision recording     | ~391   |
| `core/framework/builder/query.py`    | Pattern analysis       | ~400+  |
| `core/framework/builder/workflow.py` | Graph building         | ~600+  |
| `core/framework/schemas/run.py`      | Run data model         | ~262   |
| `core/framework/storage/backend.py`  | Persistence layer      | ~200+  |

### Configuration

- `.mcp.json`: MCP server configuration
- `core/pyproject.toml`: Dependencies & entry points
- `core/framework/cli.py`: CLI command registration

### Tests

- `core/tests/test_graph_executor.py`: Execution tests
- `core/tests/test_builder.py`: Pattern analysis tests
- `core/tests/test_event_loop_node.py`: Loop behavior tests

---

## 🔗 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ User / External System                                      │
└────────────────┬────────────────────────────────────────────┘
                 │ Input Data
                 ▼
         ┌──────────────────┐
         │   GraphExecutor  │
         └────────┬─────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
   ┌─────────────┐    ┌───────────────────┐
   │ NodeContext │    │ SharedMemory      │
   │ (for node)  │    │ (inter-node data) │
   └─────┬───────┘    └───────────────────┘
         │
         ▼
    ┌──────────────┐
    │ Execute Node │ ──────────────┐
    └──────┬───────┘               │
           │                       │
    ┌──────▼──────────┐       ┌────▼────────────┐
    │ Runtime.decide()│       │ Node processes  │
    │ (record option) │       │ logic/LLM/tools │
    └──────┬──────────┘       └────┬────────────┘
           │                       │
    ┌──────▼────────────────────────▼──────┐
    │ Runtime.record_outcome()              │
    │ (record what actually happened)       │
    └──────┬─────────────────────────────────┘
           │
           ▼
    ┌──────────────────┐
    │ Decision object  │
    │ → Add to Run     │
    └──────┬───────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Storage/FileStorage  │
    │ /runs/{run_id}.json  │
    └──────┬───────────────┘
           │
    ┌──────▼──────────────────┐
    │ Later: BuilderQuery      │
    │ - find_patterns()        │
    │ - suggest_improvements() │
    │ - analyze failures       │
    └──────┬───────────────────┘
           │
           ▼
    ┌──────────────────┐
    │ MCP Server       │
    │ (to Builder LLM) │
    └────────────────────┘
```

---

## 🎓 Learning Path

1. **Understand the Graph Model** → `docs/key_concepts/graphs.md`
2. **Read Node Protocol** → `core/framework/graph/node.py` (first 300 lines)
3. **Explore Runtime** → `core/framework/runtime/core.py`
4. **See GraphExecutor** → `core/framework/graph/executor.py` (execute method)
5. **Try an Example** → `core/examples/manual_agent.py`
6. **Build a Simple Agent** → Follow `docs/getting-started.md`
7. **Analyze Runs** → Use `BuilderQuery` to understand pattern analysis
8. **Deep Dive**: Read specific modules as needed

---

## 🤝 Common Patterns

### Pattern 1: LLM + Tools Loop

```
LLMNode(llm_tool_use)
  ↓
  LLM generates plan + calls tools
  ↓
Tools execute (searches, API calls, etc)
  ↓
LLM sees results, decides next action
  ↓
If done → Router to next node
Else → Repeat (via EventLoopNode)
```

### Pattern 2: Function Node Chain

```
FunctionNode(fetch_data)
  ↓ (output)
FunctionNode(process_data)
  ↓ (output)
LLMNode(classify)
  ↓
Router → next agent or terminal
```

### Pattern 3: Decision with Human Oversight

```
LLMNode(generate_recommendation)
  ↓
HumanInputNode(approve?)
  ├→ Approve → execute action
  ├→ Modify → revise and try again
  └→ Reject → skip to next goal
```

### Pattern 4: Multi-Agent Handoff

```
Agent A (LLMNode) solves subproblem
  ↓
ContextHandoff → Send results to Agent B
  ↓
Agent B (EventLoop) refines solution
  ↓
ContextHandoff → Results back to Agent A
  ↓
Agent A finalizes
```

---

## 🐛 Debugging & Troubleshooting

### Common Issues

| Issue                  | Cause                      | Solution                                               |
| ---------------------- | -------------------------- | ------------------------------------------------------ |
| Node timeout           | Tool too slow              | Add `max_retries`, check tool impl                     |
| High token usage       | Too much context           | Reduce history, use summarization                      |
| Decision not recorded  | Missing `runtime.decide()` | Check node impl for decision calls                     |
| Output not flowing     | Wrong output_keys          | Verify NodeSpec output_keys match next node input_keys |
| Pattern analysis empty | No runs stored             | Run agent first: `hive run ...`                        |
| Tool not found         | Tool not registered        | Check executor.tools and MCP server config             |

### Debugging Commands

```bash
# Check agent structure
hive info exports/my-agent

# Validate agent
hive validate exports/my-agent

# Run with debug logging
export PYTHONPATH=core && python -m framework.cli --debug run exports/my-agent

# Inspect a run
python -c "
from framework.storage.backend import FileStorage
storage = FileStorage('/path/to/storage')
run = storage.load_run('run-id')
for d in run.decisions:
    print(f'{d.node_id}: {d.intent} → {d.chosen}')"

# Analyze patterns
hive test-stats goal_123
```

---

## 📚 Additional Resources

- **Official Docs**: https://docs.adenhq.com/
- **GitHub Issues**: https://github.com/adenhq/hive/issues
- **Roadmap**: `docs/roadmap.md`
- **Contributing**: `CONTRIBUTING.md`
- **Security**: `SECURITY.md`

---

This document provides a comprehensive overview of the Hive codebase structure. Use it as a reference for understanding how components interact, where to find specific functionality, and how to extend or debug the framework.
