# Hive Architecture Visual Guide

## Module Dependency Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          APPLICATION LAYER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   CLI       │  │ Builder      │  │ MCP Server   │  │ Examples     │    │
│  │ (cli.py)    │  │ (workflow)   │  │ (agent_      │  │ (demos/)     │    │
│  │             │  │              │  │  builder_    │  │              │    │
│  └──────┬──────┘  │              │  │  server.py)  │  └──────────────┘    │
│         │         └──────┬───────┘  └──────┬────────┘                      │
│         │                │                 │                              │
│         └────────┬───────┴─────────────────┘                              │
│                  │                                                          │
└──────────────────┼──────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ORCHESTRATION LAYER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ GraphExecutor (executor.py)                                          │  │
│  │  - Loads GraphSpec                                                   │  │
│  │  - Initializes SharedMemory                                          │  │
│  │  - Executes nodes in sequence/parallel                               │  │
│  │  - Follows edges (routing)                                           │  │
│  │  - Handles retries & errors                                          │  │
│  │  - Manages checkpoints                                               │  │
│  └────────────┬─────────────────────────────────────────────────────────┘  │
│               │                                                              │
│  ┌────────────┼──────────────────────────────────────────────────────────┐ │
│  │            │ Registry                                                 │ │
│  │  ┌─────────▼─────────┐                                                │ │
│  │  │ Node Implementations (NodeRegistry)                                │ │
│  │  ├─────────┬─────────┬─────────┬──────────┬──────────────────────┤  │
│  │  │         │         │         │          │                      │  │
│  │  ▼         ▼         ▼         ▼          ▼                      ▼  │
│  │  LLMNode Router   Function HumanInput EventLoop    WorkerNode    │  │
│  │  - Call  - Logic   - Exec    - HITL    - Loop      - MultiStep   │  │
│  │    LLM    routing   Python              tool use    dispatch      │  │
│  │  - Tool  - Route   - Return  - Approve                           │  │
│  │    use     based    result    choice                             │  │
│  │  - Gen    on                                                     │  │
│  │    text    output                                                │  │
│  │           value                                                  │  │
│  └─────────────────────────────────────────────────────────────────┤  │
│                                                                      │  │
│  ┌──────────────────────────────────────────────────────────────┐   │  │
│  │ FlexibleGraphExecutor (flexible_executor.py)                │   │  │
│  │  - Worker-Judge pattern                                     │   │  │
│  │  - Parallel execution                                       │   │  │
│  │  - Plan + Verify workflow                                   │   │  │
│  └──────────────────────────────────────────────────────────────┘   │  │
│                                                                      │  │
└──────────────────────────────────────────────────────────────────────┘  │
                                                                           │
│                        ┌──────────┴──────────────────────┐              │
│                        │                                 │              │
└────────────────────────┼─────────────────────────────────┼──────────────┘
                         │                                 │
                         ▼                                 ▼
┌──────────────────────────────────┐   ┌──────────────────────────────┐
│      EXECUTION CONTEXT LAYER     │   │   INTEGRATION LAYER          │
├──────────────────────────────────┤   ├──────────────────────────────┤
│                                  │   │                              │
│ NodeContext (node.py)            │   │ ┌──────────────────────────┐ │
│  ├─ node_spec (what to do)       │   │ │ LLM Provider (llm/)      │ │
│  ├─ input_data (what we have)    │   │ │  ├─ Anthropic API        │ │
│  ├─ runtime (for recording)      │   │ │  ├─ OpenAI API           │ │
│  ├─ llm (for LLM calls)          │   │ │  ├─ Google Gemini API    │ │
│  ├─ tools (available)            │   │ │  └─ litellm wrapper      │ │
│  ├─ memory (scoped access)       │   │ │                          │ │
│  ├─ goal (context)               │   │ │ ┌──────────────────────┐ │ │
│  └─ ...                          │   │ │ │ Tool Registry        │ │ │
│                                  │   │ │ │  ├─ Web search        │ │ │
│ NodeResult (node.py)             │   │ │  ├─ Database query    │ │ │
│  ├─ success (did it work?)       │   │ │  ├─ API calls         │ │ │
│  ├─ output (next node input)     │   │ │  ├─ File operations   │ │ │
│  ├─ next_node (routing)          │   │ │  └─ ...               │ │ │
│  ├─ error (if failed)            │   │ │                          │ │
│  └─ tokens_used, latency_ms      │   │ └──────────────────────┘   │ │
│                                  │   │                              │
│ SharedMemory (node.py)           │   │ ┌──────────────────────────┐ │
│  ├─ Stores inter-node data       │   │ │ Credentials (credentials/│ │
│  ├─ Per-node read/write scope    │   │ │  ├─ Encrypted storage    │ │
│  └─ Prevents data leaks          │   │ │  ├─ Vault integration    │ │
│                                  │   │ │  └─ Per-node access      │ │
│ NodeConversation                 │   │ │                          │ │
│  (conversation.py)               │   │ │ ┌──────────────────────┐ │ │
│  ├─ Multi-turn history           │   │ │ │ CodeSandbox          │ │ │
│  ├─ Message store                │   │ │ │  ├─ Safe eval         │ │ │
│  └─ Role-based filtering         │   │ │  ├─ Restricted NS      │ │ │
│                                  │   │ │  └─ Configurable       │ │ │
│ ContextHandoff                   │   │ │                          │ │
│  (context_handoff.py)            │   │ └──────────────────────┘   │ │
│  ├─ Agent-to-agent passing       │   │                              │ │
│  └─ Data transformation          │   │ ┌──────────────────────────┐ │
│                                  │   │ │ Event Bus (event_bus.py) │ │
│ Goal (goal.py)                   │   │ │  ├─ Async events         │ │
│  ├─ What to achieve              │   │ │  ├─ Streaming results    │ │
│  ├─ Success criteria             │   │ │  └─ Real-time updates    │ │
│  ├─ Constraints (budget, time)   │   │ │                          │ │
│  └─ To prompt context            │   │ └──────────────────────┘   │ │
│                                  │   │                              │
└──────────────────────────────────┘   └──────────────────────────────┘
         │                                         │
         └──────────────────────┬──────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    OBSERVATION & RECORDING LAYER                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ Runtime (runtime/core.py)                                              │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │  │
│  │  │ Decision Recording   │  │ Outcome Recording                    │  │  │
│  │  │                      │  │                                      │  │  │
│  │  │ runtime.decide(      │  │ runtime.record_outcome(              │  │  │
│  │  │   intent="...",      │  │   decision_id,                       │  │  │
│  │  │   options=[...],     │  │   success=bool,                      │  │  │
│  │  │   chosen="...",      │  │   result={...},                      │  │  │
│  │  │   reasoning="..."    │  │   summary="..."                      │  │  │
│  │  │ )                    │  │ )                                    │  │  │
│  │  │ ↓                    │  │ ↓                                    │  │  │
│  │  │ Decision ID          │  │ Outcome attached to Decision         │  │  │
│  │  │ (used for outcome)   │  │                                      │  │  │
│  │  └──────────┬───────────┘  └──────────────────┬───────────────────┘  │  │
│  │             │                                 │                      │  │
│  │             └─────────────────┬───────────────┘                      │  │
│  │                               │                                      │  │
│  │                    ┌──────────▼──────────┐                          │  │
│  │                    │ Current Run         │                          │  │
│  │                    │  └─ decisions[]     │                          │  │
│  │                    │  └─ problems[]      │                          │  │
│  │                    │  └─ metrics         │                          │  │
│  │                    └─────────┬──────────┘                          │  │
│  │                              │                                      │  │
│  └──────────────────────────────┼──────────────────────────────────────┘  │
│                                 │                                          │
│  ┌──────────────────────────────▼──────────────────────────────────────┐  │
│  │ RuntimeLogger (runtime/runtime_logger.py)                          │  │
│  │  - L0: Run level (overall execution)                               │  │
│  │  - L1: Goal level (goal pursuit)                                   │  │
│  │  - L2: Node level (per-node stats)                                 │  │
│  │  - L3: Tool level (tool call details)                              │  │
│  │  - Tracks: tokens, latency, success/error                          │  │
│  └──────────────────────────────┬──────────────────────────────────────┘  │
│                                 │                                          │
└─────────────────────────────────┼──────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        PERSISTENCE LAYER                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ Storage Backend (storage/backend.py) [FileStorage default]            │  │
│  │                                                                        │  │
│  │  ├─ save_run(run)              ├─ load_run(run_id)                    │  │
│  │  ├─ list_runs()                ├─ list_goals()                        │  │
│  │  ├─ delete_run()               └─ ...                                 │  │
│  │                                                                        │  │
│  │  Stores to: storage/runs/{run_id}.json (JSON serialized)              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ CheckpointStore (storage/checkpoint_store.py)                        │  │
│  │  - Save execution state at intervals                                 │  │
│  │  - Restore from checkpoint to resume                                 │  │
│  │  - Resumable Sessions support                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
└──────────────────────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│      SCHEMAS LAYER           │  │   ANALYSIS LAYER             │
├──────────────────────────────┤  ├──────────────────────────────┤
│                              │  │                              │
│ ┌─────────────────────────┐ │  │ ┌──────────────────────────┐ │
│ │ Run (schemas/run.py)    │ │  │ │ BuilderQuery             │ │
│ │  ├─ id, status          │ │  │ │  (builder/query.py)      │ │
│ │  ├─ decisions[]         │ │  │ │                          │ │
│ │  ├─ metrics             │ │  │ │ Methods:                 │ │
│ │  ├─ problems[]          │ │  │ │  ├─ find_patterns()      │ │
│ │  └─ narrative           │ │  │ │  ├─ suggest_            │ │
│ │                         │ │  │ │  │   improvements()     │ │
│ │ ┌─────────────────────┐ │  │ │  ├─ get_decision_trace() │ │
│ │ │ Decision            │ │  │ │  ├─ compare_runs()       │ │
│ │ │ (schemas/decision.py)│ │  │ │  └─ get_node_          │ │
│ │ │  ├─ id              │ │  │ │      performance()      │ │
│ │ │  ├─ node_id         │ │  │ │                          │ │
│ │ │  ├─ intent          │ │  │ │ Results:                 │ │
│ │ │  ├─ options[]       │ │  │ │  ├─ PatternAnalysis      │ │
│ │ │  ├─ chosen          │ │  │ │  ├─ Problematic nodes    │ │
│ │ │  ├─ reasoning       │ │  │ │  ├─ Common failures      │ │
│ │ │  ├─ outcome         │ │  │ │  └─ Suggestions          │ │
│ │ │  └─ was_successful  │ │  │ │                          │ │
│ │ │                     │ │  │ └──────────────────────────┘ │
│ │ │ ┌───────────────┐   │ │  │                              │
│ │ │ │ Outcome       │   │ │  │ ┌──────────────────────────┐ │
│ │ │ │  ├─ result    │   │ │  │ │ GraphBuilder             │ │
│ │ │ │  ├─ latency   │   │ │  │ │ (builder/workflow.py)    │ │
│ │ │ │  ├─ tokens    │   │ │  │ │                          │ │
│ │ │ │  └─ error     │   │ │  │ │ Incremental building:    │ │
│ │ │ └───────────────┘   │ │  │ │  1. Define goal          │ │
│ │ │                     │ │  │ │  2. Add nodes            │ │
│ │ └─────────────────────┘ │  │ │  3. Add edges            │ │
│ │                         │ │  │ │  4. Validate & test     │ │
│ │ ┌─────────────────────┐ │  │ │  5. HITL approval        │ │
│ │ │ Checkpoint          │ │  │ │  6. Export               │ │
│ │ │ (schemas/checkpoint)│ │  │ │                          │ │
│ │ │  ├─ state snapshot  │ │  │ └──────────────────────────┘ │
│ │ │  ├─ execution point │ │  │                              │
│ │ │  └─ resumable       │ │  └──────────────────────────────┘
│ │ └─────────────────────┘ │  │
│ │                         │  │
│ └─────────────────────────┘  │
│                              │
└──────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  MCP SERVER (mcp/)           │
├──────────────────────────────┤
│                              │
│ agent_builder_server.py      │
│  - Exposes BuilderQuery      │
│  - Exposes GraphBuilder      │
│  - Callable from Claude/     │
│    Cursor code editors       │
│  - Tools:                    │
│   ├─ query_run()             │
│   ├─ find_patterns()         │
│   ├─ suggest_               │
│   │   improvements()        │
│   ├─ create_agent()          │
│   └─ test_agent()            │
│                              │
└──────────────────────────────┘
```

---

## Node Execution Sequence

```
GraphExecutor.execute(graph, goal, input_data)
│
├─ Initialize
│  ├─ Load all NodeSpec from GraphSpec
│  ├─ Initialize SharedMemory {}
│  ├─ Load Runtime (for decision logging)
│  └─ Load all Tool definitions
│
├─ Start run recording
│  └─ runtime.start_run(goal_id, ...)
│
└─ Execution Loop
   │
   ├─ [1] Find current node ID
   │  └─ Initially: graph.initial_node
   │     Later: determined by edges/routing
   │
   ├─ [2] Load NodeSpec from graph.nodes[node_id]
   │  └─ Get: node_type, system_prompt, tools, input_keys, output_keys, ...
   │
   ├─ [3] Build NodeContext
   │  ├─ input_data (filtered to input_keys)
   │  ├─ available_tools (filtered to node's tools)
   │  ├─ runtime (for decision recording)
   │  ├─ llm provider
   │  ├─ shared_memory (scoped read/write)
   │  ├─ goal context
   │  └─ ...
   │
   ├─ [4] Get node implementation from registry
   │  └─ One of: LLMNode, RouterNode, FunctionNode, EventLoopNode, HumanInputNode, WorkerNode
   │
   ├─ [5] Execute node
   │  │
   │  └─ For LLMNode:
   │     │
   │     ├─ Record decision
   │     │  └─ decision_id = runtime.decide(
   │     │      intent="Call LLM",
   │     │      options=["use_tools", "generate_text"],
   │     │      chosen="...",
   │     │      reasoning="..."
   │     │    )
   │     │
   │     ├─ Build system prompt from NodeSpec
   │     │  └─ Replace {placeholders} with context
   │     │
   │     ├─ Build messages from input + history
   │     │  ├─ Add system prompt
   │     │  ├─ Add conversation history (if multi-turn)
   │     │  └─ Add current input
   │     │
   │     ├─ Make LLM call
   │     │  ├─ Pass available_tools to LLM
   │     │  ├─ Parse response (tool_calls or generated_text)
   │     │  └─ Handle tool calls if present
   │     │      ├─ Execute each tool
   │     │      ├─ Collect results
   │     │      ├─ May loop if EventLoopNode (judge says continue)
   │     │      └─ Return final output
   │     │
   │     └─ Record outcome
   │        └─ runtime.record_outcome(
   │           decision_id,
   │           success=True,
   │           result=output_data,
   │           ...
   │        )
   │
   ├─ [6] Get NodeResult
   │  ├─ result.success: bool
   │  ├─ result.output: dict (will become next node's input)
   │  ├─ result.next_node: str (for explicit routing)
   │  ├─ result.error: str (if failed)
   │  ├─ result.tokens_used: int
   │  └─ result.latency_ms: int
   │
   ├─ [7] Handle retries if failed
   │  ├─ If result.success == False and retries < max_retries
   │  │  └─ Go back to [5], increment retry count
   │  └─ Else if max retries exceeded
   │     └─ Record problem to Runtime, continue or fail
   │
   ├─ [8] Update shared memory
   │  └─ For each key in result.output:
   │     └─ If key in NodeSpec.output_keys:
   │        └─ shared_memory[key] = result.output[key]
   │
   ├─ [9] Determine next node
   │  ├─ Option 1: Explicit routing
   │  │  └─ If result.next_node:
   │  │     └─ next_node_id = result.next_node
   │  │
   │  ├─ Option 2: Edge condition routing
   │  │  └─ For each edge from current node:
   │  │     └─ Evaluate edge.condition(result, shared_memory)
   │  │        └─ If matches:
   │  │           └─ next_node_id = edge.to_id
   │  │
   │  └─ Option 3: Terminal node check
   │     └─ If current_node_id in graph.terminal_nodes:
   │        └─ DONE - break loop
   │
   ├─ [10] Check visit limits
   │  └─ If next_node_id already visited >= max_visits:
   │     └─ Skip it, try next edge
   │
   └─ [11] Loop back to [1] with new node_id
      │
      └─ Continue until terminal node reached
         │
         └─ runtime.end_run(success=True, narrative="...")
            └─ Return ExecutionResult(success=True, output=final_output)
```

---

## Data Structure Relationships

```
GraphSpec
├─ nodes: dict[id → NodeSpec]
│  └─ NodeSpec
│     ├─ id: str
│     ├─ node_type: str ("llm_tool_use", "llm_generate", "router", "function", ...)
│     ├─ system_prompt: str | None
│     ├─ tools: list[str]  (names of available tools)
│     ├─ input_keys: list[str]  (what to read from memory)
│     ├─ output_keys: list[str]  (what to write to memory)
│     ├─ max_retries: int
│     └─ ...
│
├─ edges: dict[id → EdgeSpec]
│  └─ EdgeSpec
│     ├─ id: str
│     ├─ from_id: str (source node)
│     ├─ to_id: str (target node)
│     └─ condition: EdgeCondition  (when to follow this edge)
│        ├─ type: "output_equals", "output_contains", "custom", ...
│        └─ value: str (condition details)
│
├─ initial_node: str (starting node id)
├─ terminal_nodes: list[str] (ending node ids)
├─ tools: list[Tool]  (available tools)
└─ ...

Run (persisted in storage/runs/{run_id}.json)
├─ id: str
├─ goal_id: str
├─ status: RunStatus
├─ decisions: list[Decision]  ← ALL decisions in this run
│  └─ Decision
│     ├─ id: str (unique)
│     ├─ node_id: str (which node made this decision)
│     ├─ intent: str (what was being decided)
│     ├─ options: list[Option]
│     │  └─ Option
│     │     ├─ id: str
│     │     ├─ description: str
│     │     └─ ...
│     ├─ chosen: str (which option was picked - matches Option.id)
│     ├─ reasoning: str (why this option)
│     ├─ outcome: Outcome | None
│     │  └─ Outcome
│     │     ├─ result: dict (what actually happened)
│     │     ├─ latency_ms: int
│     │     ├─ tokens_used: int
│     │     ├─ error: str | None
│     │     └─ summary: str
│     ├─ was_successful: bool
│     ├─ decision_type: DecisionType ("tool_use", "routing", "generation", ...)
│     └─ timestamp: datetime
│
├─ metrics: RunMetrics
│  ├─ total_decisions: int
│  ├─ successful_decisions: int
│  ├─ failed_decisions: int
│  ├─ total_tokens: int
│  ├─ total_latency_ms: int
│  ├─ success_rate: float
│  └─ ...
│
├─ problems: list[Problem]
│  └─ Problem
│     ├─ id: str
│     ├─ severity: str ("critical", "warning", "minor")
│     ├─ description: str
│     ├─ root_cause: str | None
│     ├─ decision_id: str | None (which decision caused this)
│     └─ suggested_fix: str | None
│
├─ narrative: str (human summary)
└─ timestamp: datetime

SharedMemory (per execution)
└─ dict[str → Any]
   └─ Keys flow from node to node:
      Node A output_keys → shared_memory
      │
      shared_memory[key] → Node B input_keys
      │
      Node B output_keys → shared_memory
      └─ ... continue
```

---

## Self-Improvement Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                    The Self-Improvement Cycle                   │
└─────────────────────────────────────────────────────────────────┘

[1] INITIAL RUN
    $ hive run exports/my-agent --input {...}
    │
    └─ GraphExecutor executes graph
       ├─ Each node makes decision + records outcome
       ├─ All recorded to Run object
       └─ Run saved to storage/runs/{run_id}.json

[2] ANALYSIS
    BuilderQuery.find_patterns(goal_id)
    │
    ├─ Load all runs for goal_id
    ├─ Analyze decisions:
    │  ├─ Success rate: 85% (85/100 runs succeeded)
    │  ├─ Common failures: [("timeout", 10), ("no_data", 8), ...]
    │  ├─ Problematic nodes: [("classify", 0.3), ("fetch", 0.2)]
    │  └─ Decision patterns: Tool use fails when context > 8k tokens
    │
    └─ Return PatternAnalysis

[3] IMPROVEMENT SUGGESTIONS
    BuilderQuery.suggest_improvements(goal_id)
    │
    └─ For each pattern:
       ├─ Node "classify" has 30% failure rate
       │  → Suggestion: "Improve node prompt or add validation"
       │
       ├─ Common error: "timeout"
       │  → Suggestion: "Add retry logic or increase timeout"
       │
       └─ Issue: "Token overflow in tool calls"
           → Suggestion: "Add context compression or summarization"

[4] AI-DRIVEN IMPROVEMENT (Builder/Cursor)
    Builder LLM (via MCP server):
    │
    ├─ Read BuilderQuery output
    ├─ Understand failures
    ├─ Generate code changes:
    │  ├─ New system prompt for classify node
    │  ├─ Add validation step before tool use
    │  ├─ Implement context summarization
    │  └─ Better error handling
    │
    └─ Update agent code in exports/my-agent/

[5] TESTING
    $ hive test-run exports/my-agent --goal goal_123
    │
    └─ Run updated agent on test cases
       ├─ Check if failures are reduced
       ├─ Verify no regressions
       └─ Report results

[6] DEPLOYMENT
    If tests pass:
    │
    └─ Updated agent ready for production
       └─ Next runs use improved version

[7] MONITORING
    After N new runs (e.g., 20):
    │
    └─ Repeat analysis [2]
       ├─ New success rate?
       ├─ Different failure patterns?
       └─ More improvements needed?

└─ LOOP BACK TO [2]
   Continuous improvement cycle

```

---

## Integration Points

### 1. How CLI Integrates

```
Entry: $ hive run exports/my-agent --input '{"key": "value"}'
│
├─ cli.py/_configure_paths()
│  └─ Auto-discover exports/ in sys.path
│
├─ cli.py/main()
│  └─ Parse args → command="run"
│
├─ runner/cli.py/register_commands()
│  └─ Register "run" subcommand handler
│
└─ runner/cli.py/run_handler(args)
   ├─ Load agent from exports/my-agent/__init__.py
   │  └─ Import graph, goal, tools
   │
   ├─ Initialize components
   │  ├─ Runtime (for decision logging)
   │  ├─ LLM provider (from env vars)
   │  ├─ Tool registry
   │  └─ Storage backend
   │
   ├─ Create GraphExecutor
   │  └─ executor = GraphExecutor(runtime, llm, tools, ...)
   │
   ├─ Execute
   │  └─ result = await executor.execute(graph, goal, input_data)
   │
   └─ Output result
      ├─ Print to stdout
      ├─ Run saved to storage/runs/{run_id}.json
      └─ Return exit code
```

### 2. How MCP Server Integrates

```
Entry: Claude Code / Cursor
│
├─ User: "Analyze my agent's failures and suggest improvements"
│
└─ Claude uses MCP tools:
   │
   ├─ call mcp.find_patterns(goal_id="classify_leads")
   │  └─ → MCP server calls BuilderQuery.find_patterns()
   │     └─ → Returns PatternAnalysis JSON
   │
   ├─ call mcp.suggest_improvements(goal_id="classify_leads")
   │  └─ → MCP server calls BuilderQuery.suggest_improvements()
   │     └─ → Returns list of improvement suggestions
   │
   ├─ Claude understands failures
   │
   ├─ Claude modifies agent code
   │  └─ Updates exports/my-agent/nodes/classifier.py
   │
   └─ Claude calls mcp.test_agent(agent_path, test_cases)
      └─ → MCP server creates GraphExecutor and runs tests
         └─ → Returns TestResult JSON
            └─ → Claude sees if improvements worked
```

### 3. How Storage Integrates

```
During execution:
├─ runtime.start_run() → creates Run object in memory
├─ runtime.decide() → creates Decision object
├─ runtime.record_outcome() → attaches Outcome to Decision
├─ ...
└─ runtime.end_run() → finalizes Run object
   │
   └─ storage.save_run(run) → FileStorage.save_run()
      │
      ├─ Convert Run to JSON (Pydantic serialization)
      ├─ Create /storage/runs/{run_id}.json
      └─ Write file

Later, for analysis:
├─ BuilderQuery(storage_path)
│  └─ Reads from FileStorage
│     └─ Queries: storage.get_runs_by_goal(goal_id)
│
├─ For each run_id:
│  ├─ storage.load_run(run_id) → parses JSON back to Run object
│  ├─ Access run.decisions
│  ├─ Analyze patterns
│  └─ Generate suggestions
│
└─ Return results to Builder/Query
```

---

## Performance Considerations

```
Token Usage
├─ Per LLM call: tracked in Outcome.tokens_used
├─ Per run: summed in RunMetrics.total_tokens
├─ Per node: aggregated by BuilderQuery.get_node_performance()
└─ Useful for: identifying expensive nodes, budget tracking

Latency
├─ Per decision: Outcome.latency_ms
├─ Per node call: tracked separately
├─ Per run: summed in RunMetrics.total_latency_ms
└─ Useful for: identifying bottlenecks, SLA tracking

Concurrency
├─ Parallel execution: multiple nodes run simultaneously
├─ Limited by: parallel_config.max_parallel_nodes
├─ Requires: nodes to be independent (no data dependencies)
└─ Tool executor: shared across all parallel node executions

Memory
├─ SharedMemory: grows with inter-node data
├─ Conversation history: can grow in long-running agents
├─ Solution: periodic summarization, pruning old messages
└─ Checkpoint snapshots: stored for resumable execution

Storage
├─ Per run: 1 JSON file (size depends on decision count)
├─ Typical: 50-500 KB per 100-decision run
├─ Cleanup: old runs can be archived/deleted after analysis
└─ Scaling: consider database backend for large deployments
```

---

This visual guide complements the detailed codebase structure document. Use it to understand the relationships between modules and the flow of data through the system.
