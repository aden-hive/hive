# Hive for MERN Stack Developers - Quick Start Guide

## 👋 Welcome!

You have a **perfect background** for Hive:

- ✅ **Backend skills** (Node.js, async/await, APIs)
- ✅ **Frontend skills** (UI, state management, real-time updates)
- ✅ **AI fundamentals** (prompts, models, tokens)

This guide bridges your knowledge to Hive concepts.

---

## 🔀 Mapping Your Skills

### Backend (Node.js) → Hive Graph Execution

**What you know**: Node.js async functions, middlewares, request/response cycle

**Hive equivalent**:

```python
# Think of a Node like a Next.js API route
class MyNode(NodeProtocol):  # Like: export default async function handler()
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # ctx = like req (has input_data, runtime, tools)
        # return NodeResult like res.json(data)

        decision_id = ctx.runtime.decide(...)  # Like: logging middleware
        result = await self.do_work(ctx.input_data)  # Like: business logic
        ctx.runtime.record_outcome(...)  # Like: final logging

        return NodeResult(success=True, output=result)
```

**Similarity**: Linear flow, async operations, middleware-like decision recording

---

### Frontend (React) → Hive MCP Integration

**What you know**: Component state, props, hooks, real-time updates

**Hive equivalent**:

```python
# MCP Server is like a backend API for Claude Code/Cursor
# BuilderQuery is like React state (stores run/decision data)
# Agent improvements are like component re-renders

query = BuilderQuery(storage_path)  # Like: useState(initialState)

patterns = query.find_patterns(goal_id)  # Like: useEffect(() => fetch())
# patterns = { success_rate, failures, problematic_nodes }

improvements = query.suggest_improvements(goal_id)  # Like: derived state
# MCP exposes these to Claude as "tools"

# Claude calls: mcp.suggest_improvements(goal_id)
# → Updates agent code
# → Like: setState() → re-render
```

**Similarity**: Fetch data, analyze patterns, trigger changes, observe results

---

### API Development → Hive Runtime

**What you know**: Recording logs, tracking requests, error handling

**Hive equivalent**:

```python
# Hive Runtime = sophisticated logging system

runtime = Runtime("/storage/path")

# Like: logger.info("Request started")
run_id = runtime.start_run(goal_id="my_goal")

# Like: middleware recording request params
decision_id = runtime.decide(
    intent="What to do",
    options=[...],
    chosen="option_1",
    reasoning="Why"
)

# Like: middleware recording response & status
runtime.record_outcome(
    decision_id,
    success=True,
    result={"data": "..."},
    summary="What happened"
)

# Like: logger.info("Request completed")
runtime.end_run(success=True)

# All saved to: storage/runs/{run_id}.json
# Like: Structured logs you can query
```

**Similarity**: Lifecycle tracking, decision recording, structured data storage

---

## 💡 How Hive Works (In Terms You Know)

### The Agent as a Microservices Pipeline

```
┌─────────────┐
│ GraphSpec   │  ← Like: API routes config
├─────────────┤
│ • nodes[]   │  ← Like: route handlers/microservices
│ • edges[]   │  ← Like: service-to-service calls
│ • tools[]   │  ← Like: external API integrations
└──────┬──────┘
       │
       ▼
┌──────────────────────────────┐
│ GraphExecutor.execute()      │  ← Like: Express app.listen()
│                              │
│ for each node in sequence:   │
│ ├─ ctx = build context      │  ← Like: req object
│ ├─ await node.execute(ctx)  │  ← Like: handler(req, res)
│ ├─ record decision          │  ← Like: logging middleware
│ └─ update shared_memory     │  ← Like: update req.state
│                              │
│ follow edges based on        │  ← Like: Express routing
│ routing logic                │
└──────┬───────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Runtime (Decision Log)      │  ← Like: Structured logs
│                             │
│ Stores: decisions[]         │
│ Each has: intent, options,  │
│           chosen, outcome   │
└──────┬──────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Storage (FileStorage)        │  ← Like: Database
│                              │
│ /runs/{run_id}.json          │
│ All decisions saved          │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ BuilderQuery Analysis        │  ← Like: Analytics API
│                              │
│ find_patterns()              │  ← Query: success rates
│ suggest_improvements()       │  ← Query: what failed
└──────────────────────────────┘
```

---

## 🎯 Key Concepts Translated

### Concept 1: Nodes = Async Functions

**What you know**:

```javascript
// Next.js API route
export default async function handler(req, res) {
  const result = await processData(req.body);
  res.status(200).json(result);
}
```

**Hive equivalent**:

```python
class ProcessNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # ctx.input_data = like req.body
        # ctx.runtime = like logger/tracking

        result = await self.process(ctx.input_data)

        # return like res.json()
        return NodeResult(success=True, output=result)
```

### Concept 2: Shared Memory = Request Context

**What you know**:

```javascript
// Passing data through middleware chain
req.userId = decoded.userId; // Set in auth middleware
req.userData = user; // Set in user middleware

router.post("/process", (req, res) => {
  const userId = req.userId; // Available in handler
  const userData = req.userData;
});
```

**Hive equivalent**:

```python
# Node A sets output
NodeA output_keys = ["user_id", "user_data"]
output = {"user_id": 123, "user_data": {...}}

# Shared memory updated
shared_memory["user_id"] = 123
shared_memory["user_data"] = {...}

# Node B reads input
NodeB input_keys = ["user_id", "user_data"]
ctx.input_data = {"user_id": 123, "user_data": {...}}
```

### Concept 3: Decision Recording = Request Logging

**What you know**:

```javascript
// Morgan logger + custom tracking
morgan("combined")(req, res, () => {
  trackRequest({
    method: req.method,
    path: req.path,
    status: res.statusCode,
    duration: Date.now() - start,
    userId: req.user?.id,
  });
});
```

**Hive equivalent**:

```python
decision_id = runtime.decide(
    intent="Classify user",           # What we're doing (like method+path)
    options=[...],                     # What we could have done
    chosen="ml_classification",        # What we chose
    reasoning="ML model more accurate" # Why
)

# Do work...

runtime.record_outcome(
    decision_id,
    success=True,                      # Did it work
    result={"classification": "..."},  # What happened
    summary="Classified as premium"    # Human summary
)
```

### Concept 4: Self-Improvement = Analytics → Updates

**What you know**:

```javascript
// Analytics dashboard
GET /api/analytics/errors → Returns: [
  { error: "Database timeout", count: 45, trend: "up" },
  { error: "Auth failed", count: 12, trend: "down" },
]

// You read this, find the problem, update code
// Database timeout is high → add retries, increase pool
```

**Hive equivalent**:

```python
patterns = query.find_patterns("goal_id")
# Returns: {
#   common_failures: [("timeout", 45), ("auth_failed", 12)],
#   problematic_nodes: [("fetch_node", 0.3), ("process_node", 0.1)],
#   success_rate: 0.7
# }

improvements = query.suggest_improvements("goal_id")
# Returns: [
#   { type: "add_retries", target: "fetch_node", reason: "30% failure" },
#   { type: "optimize_prompt", target: "classify_node", reason: "slow" }
# ]

# Builder LLM (Claude) reads these, makes improvements automatically
# Like: Deploy new version based on analytics
```

---

## 🔧 Building Your First Agent (Step by Step)

### Step 1: Think Like Building an API

**Requirement**: "Classify sales leads as hot/warm/cold based on company data"

**API approach**:

```javascript
// routes/classify.js
router.post("/classify", async (req, res) => {
  const { companyId } = req.body;

  // Call DB to fetch company
  const company = await db.companies.findById(companyId);

  // Call LLM to classify
  const classification = await llm.classify(company);

  // Save to DB
  await db.classifications.create({ ...classification });

  res.json({ classification });
});
```

**Hive approach** (same logic, graph form):

```python
# Define graph structure (like route config)
graph = GraphSpec(
    id="lead_classifier",
    nodes={
        "fetch_company": NodeSpec(
            node_type="function",
            function="fetch_from_db"
        ),
        "classify": NodeSpec(
            node_type="llm_tool_use",
            system_prompt="Classify companies as hot/warm/cold"
        ),
        "save": NodeSpec(
            node_type="function",
            function="save_to_db"
        )
    },
    edges={
        "fetch_to_classify": EdgeSpec(from_id="fetch_company", to_id="classify"),
        "classify_to_save": EdgeSpec(from_id="classify", to_id="save")
    }
)

# Run it
executor = GraphExecutor(runtime, llm, tools)
result = await executor.execute(graph, goal, {"company_id": "123"})
```

---

### Step 2: Implement Nodes Like Route Handlers

```python
# Node 1: Fetch company (like GET /companies/:id)
class FetchCompanyNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Record what we're about to do (like request log)
        decision_id = ctx.runtime.decide(
            intent="Fetch company data",
            options=[
                {"id": "db", "description": "Query database"},
                {"id": "cache", "description": "Use cached data"}
            ],
            chosen="db",
            reasoning="Need fresh data"
        )

        try:
            # Do the work
            company = await self.db.companies.find(ctx.input_data["company_id"])

            # Record outcome (like response log)
            ctx.runtime.record_outcome(
                decision_id,
                success=True,
                result={"company": company}
            )

            # Return like res.json()
            return NodeResult(
                success=True,
                output={"company": company}  # Goes to shared_memory
            )
        except Exception as e:
            ctx.runtime.record_outcome(decision_id, success=False, error=str(e))
            return NodeResult(success=False, error=str(e))

# Node 2: Classify (calls LLM)
class ClassifyNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        company = ctx.input_data["company"]  # From shared_memory

        decision_id = ctx.runtime.decide(
            intent="Classify company",
            options=[
                {"id": "ml", "description": "Use ML classifier"},
                {"id": "rules", "description": "Use rule-based classifier"}
            ],
            chosen="ml",
            reasoning="ML more accurate"
        )

        # Use LLM (via ctx.llm)
        classification = await ctx.llm.call(
            system="You classify companies as hot/warm/cold",
            user=f"Classify: {company['name']}, {company['size']} employees",
            tools=["web_search"]  # Available tools
        )

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"classification": classification}
        )

        return NodeResult(
            success=True,
            output={"classification": classification}
        )

# Node 3: Save (like POST to save result)
class SaveNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        classification = ctx.input_data["classification"]

        decision_id = ctx.runtime.decide(
            intent="Save classification",
            options=[{"id": "save", "description": "Save to database"}],
            chosen="save",
            reasoning="Required"
        )

        saved = await self.db.classifications.create(classification)

        ctx.runtime.record_outcome(decision_id, success=True)
        return NodeResult(success=True, output={"id": saved.id})
```

---

### Step 3: Run It Like You'd Call an API

```python
# Setup
runtime = Runtime("/path/to/storage")
llm = LLMProvider("anthropic", model="claude-opus")
executor = GraphExecutor(runtime=runtime, llm=llm)

# Register nodes
executor.register_node("fetch_company", FetchCompanyNode(db=my_db))
executor.register_node("classify", ClassifyNode())
executor.register_node("save", SaveNode(db=my_db))

# Execute (like POST /classify)
result = await executor.execute(
    graph=graph,
    goal=Goal(id="classify_leads", description="Classify sales leads"),
    input_data={"company_id": "123"}
)

# Result is like response
print(f"Success: {result.success}")
print(f"Classification ID: {result.output['id']}")
```

---

### Step 4: Analyze Like You'd Check Logs

```python
# After running 100 times:
query = BuilderQuery("/path/to/storage")

patterns = query.find_patterns("classify_leads")
print(f"Success rate: {patterns.success_rate:.1%}")  # 85%
print(f"Common failures: {patterns.common_failures}")
# → [("timeout", 15), ("invalid_data", 8)]

print(f"Problematic nodes: {patterns.problematic_nodes}")
# → [("classify", 0.3), ("fetch_company", 0.1)]

# Get suggestions
improvements = query.suggest_improvements("classify_leads")
# → [
#   { type: "timeout_handling", target: "fetch_company", reason: "15 failures" },
#   { type: "input_validation", target: "classify", reason: "30% failure rate" }
# ]

# Builder LLM reads these, updates nodes, deploys new version
```

---

## 🔄 Self-Improvement Loop (Like DevOps Deployment)

### Traditional Approach (What You Know)

```
Code → Push → GitHub CI/CD → Tests → Deploy
       ↓ if fails
    Read logs → Update code → Retry

Manual, slow, requires human decision
```

### Hive Approach (Automatic Self-Improvement)

```
Agent runs (100 executions)
    ↓
All decisions logged to storage
    ↓
BuilderQuery analyzes patterns
    ↓
Improvement suggestions generated
    ↓
Builder LLM (Claude) reads suggestions
    ↓
Claude updates nodes/prompts automatically
    ↓
New version deployed
    ↓
Run again → Measure improvement
    ↓ if improvements help
Repeat cycle

Automatic, fast, self-improving
```

---

## 📊 MERN → Hive Mapping Table

| MERN Concept          | Hive Equivalent                | Purpose           |
| --------------------- | ------------------------------ | ----------------- |
| Express route handler | Node (execute method)          | Unit of work      |
| req object            | NodeContext                    | Execution context |
| res.json()            | NodeResult                     | Return value      |
| Middleware chain      | Graph edges                    | Sequential flow   |
| req.body              | shared_memory                  | Inter-node data   |
| Express app.listen()  | GraphExecutor.execute()        | Start execution   |
| Morgan logger         | Runtime.decide()               | Track decisions   |
| Request logs          | Run + Decision objects         | Audit trail       |
| Log analysis          | BuilderQuery                   | Pattern detection |
| Manual debugging      | Automated suggestions          | Find problems     |
| Git push → deploy     | BuilderQuery → Claude → deploy | Deployment        |

---

## 💻 Setup for Your Machine

### Prerequisites

```bash
# You already have
✅ Node.js/npm knowledge
✅ Async/await understanding
✅ API development experience

# You need
⚠️ Python 3.11+ (Hive is Python, but similar concepts)
⚠️ Understanding of graph concepts (nodes + edges)
⚠️ Basic LLM knowledge (you have this!)
```

### Install Hive

```bash
# Clone
git clone https://github.com/adenhq/hive.git
cd hive

# Quick setup (requires bash/WSL on Windows)
./quickstart.sh

# Or manual setup
cd core
uv pip install -e .

# Test
hive run examples/templates/basic_agent
```

---

## 🎯 Your Learning Path (1-2 Weeks)

### Week 1: Day-by-Day

**Day 1: Foundations (1-2 hours)**

- [ ] Read: START_HERE.md (5 min)
- [ ] Read: README_CODEBASE_GUIDES.md (20 min)
- [ ] Review: This guide (20 min)
- [ ] Run: `hive run examples/templates/basic_agent` (10 min)
- [ ] Understand: How nodes are like route handlers

**Day 2: Execution (2-3 hours)**

- [ ] Study: ARCHITECTURE_VISUAL.md (20 min)
- [ ] Trace: GraphExecutor.execute() method (30 min)
- [ ] Compare: With Express middleware chain
- [ ] Implement: Simple custom node (60 min)

**Day 3: Recording (2 hours)**

- [ ] Understand: Runtime.decide() and record_outcome()
- [ ] Compare: With your logging systems
- [ ] Trace: How decisions flow into Run objects
- [ ] Implement: Node with decision recording (60 min)

**Day 4: Building (2-3 hours)**

- [ ] Review: GraphBuilder workflow
- [ ] Build: Your first graph (1-2 hours)
- [ ] Test: Run it multiple times
- [ ] Debug: Fix any issues

**Day 5: Analysis (2 hours)**

- [ ] Learn: BuilderQuery API
- [ ] Analyze: Your agent's performance
- [ ] Compare: Multiple runs
- [ ] Generate: Improvement suggestions

**Days 6-7: Integration (3-5 hours)**

- [ ] Build: More complex agent
- [ ] Iterate: Based on patterns
- [ ] Optimize: Prompts and nodes
- [ ] Deploy: Final version

### Week 2: Advanced

- Parallel execution
- Human-in-the-loop nodes
- Multi-agent coordination
- Production deployment
- Custom storage backends

---

## 🚀 Quick Project Ideas (Build These)

### Project 1: Data Classification Agent (3 hours)

**Goal**: Classify data based on rules + LLM

**Nodes**:

1. Fetch data
2. Apply rules (router)
3. Call LLM if ambiguous
4. Save classification

**Skills learned**: Graph building, routing, decision recording

### Project 2: Customer Support Agent (4-5 hours)

**Goal**: Route support tickets to appropriate team

**Nodes**:

1. Extract intent from ticket
2. Route to specialist (router)
3. Generate response (LLM)
4. Get human approval (HITL)
5. Send response

**Skills learned**: LLM integration, human-in-the-loop, complex routing

### Project 3: Data Processing Pipeline (6+ hours)

**Goal**: Multi-step data processing with quality checks

**Nodes**:

1. Fetch data (function)
2. Validate (router)
3. Transform (LLM or function)
4. Validate output (router)
5. Save (function)

**Skills learned**: Multi-step flows, validation, error handling

---

## 🔗 What You Already Know That Applies

### You Know Async/Await

```python
# Hive nodes are async functions (same pattern!)
async def execute(self, ctx: NodeContext) -> NodeResult:
    result = await some_async_operation()
    return result
```

### You Know Request/Response

```python
# NodeContext is like req, NodeResult is like res
NodeContext = request (has input_data, runtime, llm, tools)
NodeResult = response (has success, output, error)
```

### You Know Error Handling

```python
# Same try/catch pattern
try:
    result = await node.execute(ctx)
except Exception as e:
    return NodeResult(success=False, error=str(e))
```

### You Know Data Flow

```python
# Like req → middleware chain → res
Node1.output → shared_memory → Node2.input
```

### You Know Analytics

```python
# Like your analytics dashboards
query.find_patterns() → get failure rates, common errors
query.suggest_improvements() → what to fix
```

---

## 🎓 Important Files to Know

| File               | Like          | Purpose             |
| ------------------ | ------------- | ------------------- |
| executor.py        | Express app   | Runs the graph      |
| node.py            | Route handler | Node implementation |
| runtime/core.py    | Logger        | Records decisions   |
| builder/query.py   | Analytics API | Analyzes patterns   |
| storage/backend.py | Database      | Stores runs         |

---

## ⚡ Quick Reference

### Create a Node

```python
from framework.graph import NodeProtocol, NodeContext, NodeResult

class MyNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Do work
        return NodeResult(success=True, output={...})
```

### Record a Decision

```python
decision_id = ctx.runtime.decide(
    intent="What are we doing?",
    options=[{"id": "opt1", "description": "Option 1"}],
    chosen="opt1",
    reasoning="Why opt1"
)
# Do work...
ctx.runtime.record_outcome(decision_id, success=True, result={...})
```

### Build a Graph

```python
graph = GraphSpec(
    nodes={"node1": NodeSpec(...), "node2": NodeSpec(...)},
    edges={"edge1": EdgeSpec(from_id="node1", to_id="node2")},
    initial_node="node1",
    terminal_nodes=["node2"]
)
```

### Analyze Performance

```python
query = BuilderQuery(storage_path)
patterns = query.find_patterns("goal_id")
improvements = query.suggest_improvements("goal_id")
```

---

## 🤔 Common Questions

**Q: Is Python like JavaScript?**  
A: Very similar! Async/await is the same. Main difference: indentation instead of braces.

**Q: Do I need to learn Python well?**  
A: Basics are enough. Focus on concepts, not syntax.

**Q: Is Hive like Express?**  
A: Similar in spirit. Both have middleware chains and request handling. Hive is more sophisticated.

**Q: Can I use JavaScript/Node in Hive?**  
A: Not directly. Hive is Python. But you can call Node services via tools.

**Q: How is this different from my API?**  
A: Your API is transactional. Hive is agentic (autonomous, self-improving, decision-focused).

**Q: Can I deploy Hive like I deploy Express?**  
A: Yes! Via Docker, systemd, or serverless (with some adaptation).

---

## ✨ Your Superpowers (As a MERN Dev)

✅ You understand **async operations** (nodes are async functions)  
✅ You understand **data flow** (like req → middleware → res)  
✅ You understand **error handling** (same try/catch patterns)  
✅ You understand **logging/tracking** (Runtime is sophisticated logging)  
✅ You understand **analytics** (BuilderQuery is like your dashboards)  
✅ You understand **deployment** (same DevOps principles)  
✅ You understand **real-time updates** (event bus like WebSockets)

**You're in a great position to learn Hive quickly!**

---

## 🚀 Next Steps (Right Now)

1. **Open**: `START_HERE.md` in your editor
2. **Read**: This entire guide (20-30 min)
3. **Install**: Hive locally
4. **Run**: `hive run examples/templates/basic_agent`
5. **Understand**: How it maps to API concepts you know
6. **Build**: Your first custom node (60 min)
7. **Iterate**: Follow the week-long learning path

---

## 📞 Resources

- **Main documentation**: CODEBASE_STRUCTURE.md
- **Visual guide**: ARCHITECTURE_VISUAL.md
- **Quick answers**: QUICK_REFERENCE.md
- **Examples**: `core/examples/` and `examples/templates/`
- **Tests**: `core/tests/` (great for learning!)

---

**You've got this! Your MERN background is perfect for Hive. Start building! 🚀**

_This guide created: February 10, 2026_  
_For: MERN developers learning Hive_  
_Time to proficiency: 1-2 weeks_
