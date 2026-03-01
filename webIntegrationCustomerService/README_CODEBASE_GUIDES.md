# Hive Codebase Understanding - Complete Overview

## 📋 What You Have Here

I've created **3 comprehensive guides** to help you understand the Hive codebase:

### 1. **CODEBASE_STRUCTURE.md** (This is the main reference)

- **100+ sections** covering every major component
- **High-level architecture** with ASCII diagrams
- **Deep dives** into each module and subsystem
- **Execution flows** showing how data moves through the system
- **Extension points** for customization
- **Security & safety** considerations
- **Learning path** recommendations
- **Common patterns** for building agents

**Use this when you want**: Deep understanding of how something works, where to find specific functionality, or how to extend the framework.

### 2. **ARCHITECTURE_VISUAL.md** (Visual reference)

- **Module dependency map** showing how components connect
- **Node execution sequence** with step-by-step flow
- **Data structure relationships** and how they interact
- **Self-improvement loop** visualization
- **Integration points** showing how CLI, MCP, and storage connect
- **Performance considerations** and metrics

**Use this when you want**: To see the big picture, understand how pieces fit together, or trace data flow through the system.

### 3. **QUICK_REFERENCE.md** (Practical guide)

- **Most important files** you need to know (with table)
- **Quick import guide** for common imports
- **Copy-paste code patterns** for common tasks
- **Common questions & answers**
- **Node type reference** with examples
- **Testing patterns**
- **File organization cheat sheet**
- **Debugging checklist**

**Use this when you want**: To quickly find the answer to a specific question or get code snippets for common tasks.

---

## 🎯 Hive in 30 Seconds

**Hive** is a framework for building autonomous AI agents that:

1. **Execute as graphs**: Nodes represent units of work (LLM calls, functions, routing)
2. **Record everything**: Every decision is logged → enables analysis
3. **Self-improve**: Analyze patterns in failures → suggest improvements → repeat
4. **Stay observable**: Real-time monitoring, human-in-the-loop, cost tracking

**The magic**: Decision recording + Builder LLM = Continuous improvement

---

## 🏗️ Core Architecture (Simplified)

```
┌─────────────────────────────────────────────┐
│  GraphExecutor (Orchestrator)               │
│  - Loads graph spec                         │
│  - Executes nodes sequentially              │
│  - Follows edges based on routing logic     │
│  - Records all decisions                    │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
   ┌────────┐    ┌───────────────┐
   │ Nodes  │    │ Runtime       │
   │        │    │               │
   │ • LLM  │    │ Records:      │
   │ • Func │    │ • Decision ID │
   │ • Route│    │ • Options     │
   │ • Loop │    │ • Chosen      │
   │ • HITL │    │ • Outcome     │
   └────────┘    └───┬───────────┘
                     │
                     ▼
              ┌──────────────┐
              │  Storage     │
              │ (runs/...)   │
              └──────┬───────┘
                     │
                     ▼
           ┌─────────────────────┐
           │  BuilderQuery       │
           │                     │
           │ Analyzes patterns   │
           │ Suggests fixes      │
           └─────────────────────┘
                     │
                     ▼
           ┌─────────────────────┐
           │  Builder LLM        │
           │ (Claude Code)       │
           │                     │
           │ Makes improvements  │
           └─────────────────────┘
```

---

## 📁 Key Directories (You'll Visit These Most)

```
core/framework/
├── graph/              ← Node execution engine (executor.py, node.py)
├── runtime/            ← Decision recording system (core.py)
├── builder/            ← Self-improvement system (query.py, workflow.py)
├── schemas/            ← Data models (decision.py, run.py)
├── storage/            ← Persistence (backend.py)
├── llm/                ← LLM abstraction (provider.py)
├── mcp/                ← Builder interface (agent_builder_server.py)
└── credentials/        ← Credential management

core/tests/            ← 50+ test files (learn from these!)
core/examples/         ← Working code examples
examples/templates/    ← Starter agent templates
docs/                  ← Comprehensive documentation
```

---

## 🔑 The 5 Most Important Files

1. **`core/framework/graph/executor.py`** (Main engine)
   - How agents actually run
   - The execute() method is the heart of everything
   - ~1000 lines

2. **`core/framework/runtime/core.py`** (Decision API)
   - How decisions get recorded
   - Interface all nodes use
   - ~391 lines

3. **`core/framework/builder/query.py`** (Analysis)
   - How patterns are found
   - How improvements are suggested
   - ~400+ lines

4. **`core/framework/graph/node.py`** (Node Protocol)
   - How nodes are implemented
   - Node types: LLM, Router, Function, etc
   - ~1968 lines

5. **`core/framework/schemas/run.py`** (Data Model)
   - What gets stored
   - Decision, Outcome, Run structures
   - ~262 lines

---

## 🚀 The Execution Flow (Simplified)

```
1. User: hive run exports/my-agent --input {...}

2. CLI loads agent from exports/
   ├─ GraphSpec (node & edge definitions)
   ├─ Goal (what to achieve)
   ├─ Tools (available functions)
   └─ Nodes (custom implementations)

3. GraphExecutor initializes
   ├─ Creates Runtime (for recording)
   ├─ Initializes SharedMemory ({})
   └─ Starts execution loop

4. For each node in sequence:
   ├─ Load NodeSpec (configuration)
   ├─ Build NodeContext (everything node needs)
   ├─ Execute node:
   │  ├─ runtime.decide(intent, options, chosen, reasoning)
   │  ├─ Do the work (call LLM, execute function, etc)
   │  └─ runtime.record_outcome(decision_id, success, result)
   ├─ Get NodeResult (success, output, next_node)
   └─ Update SharedMemory with output

5. Determine next node
   ├─ Check if terminal node → Done
   ├─ Check explicit routing (result.next_node)
   ├─ Check edges (condition-based routing)
   └─ Repeat step 4

6. End of execution
   ├─ Finalize Run object
   ├─ Save to storage/runs/{run_id}.json
   ├─ Return ExecutionResult
   └─ Print output

7. Later: Analysis phase
   ├─ BuilderQuery analyzes all runs for goal
   ├─ Find patterns (success rate, failures, etc)
   ├─ Suggest improvements
   └─ Builder LLM makes code changes

8. Next run with improvements
   └─ Repeat from step 1
```

---

## 💡 Key Concepts to Understand

### 1. **Graphs**

- **GraphSpec**: Definition (nodes + edges)
- **Nodes**: Units of work (LLM calls, functions, routing, human input)
- **Edges**: Connections between nodes with optional conditions
- **Goal**: What the agent is trying to achieve

### 2. **Decision Recording** (The Innovation)

Every node must record:

- **Before**: What decision are we making? What are the options?
- **After**: What did we actually choose? What happened?

This creates a **complete trace** of agent reasoning → enables analysis.

### 3. **Shared Memory** (Inter-Node Communication)

- Nodes communicate via scoped, typed memory
- Node A outputs → Shared Memory → Node B inputs
- Prevents accidental data leaks with input/output key filtering

### 4. **Self-Improvement Loop**

- Run agent → Decisions saved
- Analyze patterns (success rate, failures, bottlenecks)
- Builder LLM reads patterns → generates improvements
- Deploy improvements → Repeat

### 5. **Event Loop** (Multi-Turn Tool Use)

- LLM generates plan + first tool call
- Judge decides: continue or stop?
- If continue: run tool, feed result back to LLM, repeat
- If stop: return output to next node

---

## 🛠️ Common Tasks & Where to Look

| Task                        | Look Here                                                |
| --------------------------- | -------------------------------------------------------- |
| Implement a custom node     | `core/framework/graph/node.py` (see LLMNode for example) |
| Add a new tool              | `core/framework/llm/provider.py`                         |
| Understand execution flow   | `core/framework/graph/executor.py` (execute method)      |
| Record decisions            | `core/framework/runtime/core.py` (runtime.decide)        |
| Analyze agent performance   | `core/framework/builder/query.py`                        |
| Build graph incrementally   | `core/framework/builder/workflow.py`                     |
| Store/retrieve runs         | `core/framework/storage/backend.py`                      |
| Set up MCP for Builder      | `core/framework/mcp/agent_builder_server.py`             |
| Handle credentials securely | `core/framework/credentials/`                            |
| See working example         | `core/examples/manual_agent.py`                          |
| Learn by testing            | `core/tests/test_graph_executor.py`                      |

---

## 🎓 Recommended Learning Order

### Week 1: Foundations

- Day 1: Read `CODEBASE_STRUCTURE.md` sections 1-3 (Overview, Architecture, Directory Structure)
- Day 2: Read `ARCHITECTURE_VISUAL.md` (understand module relationships)
- Day 3: Look at `core/framework/graph/node.py` (first 300 lines - understand NodeProtocol)
- Day 4: Look at `core/framework/runtime/core.py` (understand decision recording)
- Day 5: Run `hive run examples/templates/basic_agent` (see it in action)

### Week 2: Deep Dive

- Day 6: Trace through `GraphExecutor.execute()` method
- Day 7: Implement a simple custom node
- Day 8: Look at `core/tests/test_graph_executor.py` (see how things should work)
- Day 9: Understand `BuilderQuery.find_patterns()`
- Day 10: Run agent multiple times and analyze with `BuilderQuery`

### Week 3: Building

- Days 11-12: Build a custom agent using `GraphBuilder`
- Days 13-14: Implement custom nodes for your use case
- Day 15: Set up MCP integration for Builder/Cursor

### Week 4: Production

- Days 16-17: Handle errors and edge cases
- Day 18: Configure credentials and access control
- Day 19: Set up monitoring and cost tracking
- Day 20: Deploy and iterate

---

## 🔗 Most Important Code Snippets

### Recording a Decision (Every Node Should Do This)

```python
decision_id = ctx.runtime.decide(
    intent="What are we trying to accomplish?",
    options=[
        {"id": "opt1", "description": "Option 1"},
        {"id": "opt2", "description": "Option 2"},
    ],
    chosen="opt1",
    reasoning="We chose option 1 because..."
)

# Do work here...

ctx.runtime.record_outcome(
    decision_id,
    success=True,
    result={"output": "..."},
    summary="What happened"
)
```

### Implementing a Node

```python
from framework.graph import NodeProtocol, NodeContext, NodeResult

class MyNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Record decision
        decision_id = ctx.runtime.decide(...)

        # Do work
        try:
            result = await self.do_work(ctx.input_data)

            # Record outcome
            ctx.runtime.record_outcome(decision_id, success=True, ...)

            return NodeResult(success=True, output={"result": result})
        except Exception as e:
            ctx.runtime.record_outcome(decision_id, success=False, error=str(e))
            return NodeResult(success=False, error=str(e))
```

### Analyzing Patterns

```python
from framework.builder import BuilderQuery

query = BuilderQuery("/path/to/storage")
patterns = query.find_patterns("goal_123")

print(f"Success rate: {patterns.success_rate:.1%}")
print(f"Common failures: {patterns.common_failures}")
print(f"Problematic nodes: {patterns.problematic_nodes}")

improvements = query.suggest_improvements("goal_123")
```

### Running an Agent Programmatically

```python
from framework.graph import GraphExecutor
from framework.runtime import Runtime

runtime = Runtime("/path/to/storage")
executor = GraphExecutor(runtime=runtime, llm=llm, tools=tools)

result = await executor.execute(
    graph=graph_spec,
    goal=goal,
    input_data={"key": "value"}
)

print(f"Success: {result.success}")
print(f"Output: {result.output}")
```

---

## 🐛 When Things Go Wrong

| Problem                | Check                                                      |
| ---------------------- | ---------------------------------------------------------- |
| Node not executing     | Is it registered? `executor.register_node(id, impl)`       |
| Data not flowing       | Check `output_keys` and `input_keys` match                 |
| Decision not saved     | Did you call `runtime.decide()` and `record_outcome()`?    |
| Run not in storage     | Check storage path, confirm `runtime.end_run()` was called |
| Pattern analysis empty | Run agent first, then analyze. Need runs to analyze.       |
| Tool not found         | Check `executor.tools` list, verify tool name              |
| LLM failing            | Check API keys in environment variables                    |
| Timeout                | Reduce context, increase timeout, add retries              |

---

## 📚 Where to Find Each Type of Information

| Type                | Location                                    |
| ------------------- | ------------------------------------------- |
| **Concepts**        | `docs/key_concepts/`                        |
| **API Reference**   | Module docstrings + `CODEBASE_STRUCTURE.md` |
| **Examples**        | `core/examples/` + `examples/templates/`    |
| **Tests**           | `core/tests/` (great for learning!)         |
| **Architecture**    | `ARCHITECTURE_VISUAL.md`                    |
| **Quick Answer**    | `QUICK_REFERENCE.md`                        |
| **Deep Dive**       | `CODEBASE_STRUCTURE.md`                     |
| **Configuration**   | `docs/configuration.md`                     |
| **Troubleshooting** | `docs/developer-guide.md`                   |
| **Contributing**    | `CONTRIBUTING.md`                           |

---

## ✅ Verification Checklist

After reading these guides, you should be able to:

- [ ] Explain what a GraphSpec is
- [ ] Explain what a Node is and how it executes
- [ ] Explain how decisions get recorded
- [ ] Explain how Shared Memory works
- [ ] Explain how edge routing works
- [ ] Explain the self-improvement loop
- [ ] Find any file in the codebase by name
- [ ] Implement a simple custom node
- [ ] Run an existing agent
- [ ] Analyze agent performance with BuilderQuery
- [ ] Understand what would happen if you modified a node
- [ ] Know how to add a new tool
- [ ] Know where to look for specific functionality
- [ ] Understand how the MCP server exposes Hive to Builder
- [ ] Know the security considerations

---

## 🎯 Next Steps

### Option 1: Learn by Doing

1. Look at `core/examples/manual_agent.py`
2. Create a simple agent in `exports/my-agent/`
3. Run it: `hive run exports/my-agent --input {...}`
4. Analyze results: `query.find_patterns("goal_id")`
5. Make improvements: Edit nodes and test again

### Option 2: Study the Code

1. Start with `core/framework/graph/executor.py`
2. Find the `execute()` method
3. Trace through what happens at each step
4. Cross-reference with `node.py` to see how nodes work
5. Look at `runtime/core.py` to see how decisions are recorded

### Option 3: Run the Tests

1. Open `core/tests/test_graph_executor.py`
2. Read a test that interests you
3. Run it: `pytest core/tests/test_graph_executor.py::TestName`
4. Modify the test to understand behavior
5. Change the implementation to make the test fail, then fix it

### Option 4: Build Something

1. Define a goal: "Classify customer feedback"
2. Use `GraphBuilder` to create a graph
3. Implement custom nodes for your logic
4. Run it multiple times
5. Analyze and iterate

---

## 📞 Resources

- **GitHub**: https://github.com/adenhq/hive
- **Docs**: https://docs.adenhq.com/
- **Issues**: Report bugs or ask questions
- **Discussions**: Ask the community
- **Roadmap**: `docs/roadmap.md`

---

## 📝 Document Reference

| Document                 | Purpose                 | Best For           |
| ------------------------ | ----------------------- | ------------------ |
| `CODEBASE_STRUCTURE.md`  | Comprehensive reference | Deep understanding |
| `ARCHITECTURE_VISUAL.md` | Visual relationships    | Seeing connections |
| `QUICK_REFERENCE.md`     | Practical guide         | Quick lookups      |
| This file                | Overview & navigation   | Getting started    |

---

## 🏁 You're Ready!

You now have:

1. ✅ **3 comprehensive guides** covering every major aspect
2. ✅ **High-level overview** of how everything fits together
3. ✅ **Quick reference** for common questions
4. ✅ **Visual diagrams** showing architecture and flow
5. ✅ **Code examples** for common patterns
6. ✅ **Learning recommendations** for progressive learning
7. ✅ **File navigation** to find anything quickly

**Start with**: Reading `CODEBASE_STRUCTURE.md` sections 1-3, then run an example, then dive deeper as needed.

**Questions?** Check `QUICK_REFERENCE.md` first, then search in `CODEBASE_STRUCTURE.md`.

**Lost?** Refer to the file organization section in `QUICK_REFERENCE.md`.

**Happy coding!** 🚀

---

_Created: February 10, 2026_  
_For: Hive v0.4.2_  
_Audience: Developers learning the Hive codebase_
