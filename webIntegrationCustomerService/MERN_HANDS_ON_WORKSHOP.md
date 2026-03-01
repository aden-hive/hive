# MERN Developer - Hands-On Workshop

## 🎯 Learn by Building

This workshop teaches Hive concepts through **4 hands-on projects**, each building on the previous one.

---

## Project 0: Hello World Node (30 minutes)

**Goal**: Create your first custom node and run it

### Step 1: Create the Node File

Create `my_first_node.py`:

```python
from framework.graph import NodeProtocol, NodeContext, NodeResult
import time

class HelloWorldNode(NodeProtocol):
    """Your first custom node - like a simple Express route handler"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Execute the node

        ctx = like Express req (has input_data, runtime, llm, tools)
        return NodeResult = like res.json({...})
        """

        # Get input (like req.body)
        name = ctx.input_data.get("name", "World")

        # Record what we're about to do (like logging middleware)
        decision_id = ctx.runtime.decide(
            intent="Generate greeting",
            options=[
                {"id": "hello", "description": "Use 'Hello'"},
                {"id": "hi", "description": "Use 'Hi'"}
            ],
            chosen="hello",
            reasoning="More formal"
        )

        # Do the work (like business logic)
        start = time.time()
        greeting = f"Hello, {name}!"
        latency_ms = int((time.time() - start) * 1000)

        # Record outcome (like logging response)
        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"greeting": greeting},
            summary=f"Generated greeting for {name}"
        )

        # Return result (like res.json({...}))
        return NodeResult(
            success=True,
            output={"greeting": greeting},
            tokens_used=0,
            latency_ms=latency_ms
        )
```

### Step 2: Create the Graph

Create `hello_world_graph.py`:

```python
from framework.graph import GraphSpec, NodeSpec, Goal

# Define graph (like API routes config)
hello_world_graph = GraphSpec(
    id="hello_world",
    name="Hello World Agent",
    description="Simple greeting agent",
    nodes={
        "greet": NodeSpec(
            id="greet",
            name="Greeting Node",
            node_type="function",
            input_keys=["name"],
            output_keys=["greeting"]
        )
    },
    edges={},
    initial_node="greet",
    terminal_nodes=["greet"],
    tools=[]
)

# Define goal (what the agent should achieve)
goal = Goal(
    id="greet_user",
    description="Greet the user warmly",
    success_criteria=[
        {"metric": "greeting_generated", "threshold": 1}
    ]
)
```

### Step 3: Execute It

Create `run_hello.py`:

```python
import asyncio
from framework.graph import GraphExecutor
from framework.runtime import Runtime
from my_first_node import HelloWorldNode
from hello_world_graph import hello_world_graph, goal

async def main():
    # Setup (like Express setup)
    storage_path = "/tmp/hive_demo"
    runtime = Runtime(storage_path)

    # Create executor (like Express app)
    executor = GraphExecutor(runtime=runtime)

    # Register nodes (like app.use(handler))
    executor.register_node("greet", HelloWorldNode())

    # Execute (like app.listen() + handle request)
    result = await executor.execute(
        graph=hello_world_graph,
        goal=goal,
        input_data={"name": "Alice"}
    )

    # Get result (like res.json())
    print(f"Success: {result.success}")
    print(f"Greeting: {result.output.get('greeting')}")
    print(f"Run ID: {result.run_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 4: Run It

```bash
cd core
python ../run_hello.py
```

**Output**:

```
Success: True
Greeting: Hello, Alice!
Run ID: run-xxx
```

### What You Learned

✅ How to create a custom node  
✅ How decision recording works  
✅ How to execute a graph  
✅ Data is saved to storage

---

## Project 1: Multi-Node Pipeline (1-2 hours)

**Goal**: Build a 3-node pipeline with data flowing between them

### Scenario: User Verification Pipeline

```
Fetch User → Verify Email → Send Welcome
```

### Node 1: Fetch User

```python
class FetchUserNode(NodeProtocol):
    """Simulates database lookup - like a GET /users/:id endpoint"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        user_id = ctx.input_data["user_id"]

        decision_id = ctx.runtime.decide(
            intent="Fetch user from database",
            options=[
                {"id": "db", "description": "Query database"},
                {"id": "cache", "description": "Check cache first"}
            ],
            chosen="db",
            reasoning="Need fresh data"
        )

        # Simulate DB lookup
        user = {
            "id": user_id,
            "name": "Alice",
            "email": "alice@example.com",
            "created_at": "2024-01-01"
        }

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"user": user}
        )

        return NodeResult(
            success=True,
            output={"user": user}
        )
```

### Node 2: Verify Email

```python
class VerifyEmailNode(NodeProtocol):
    """Validates email - like a middleware doing validation"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        user = ctx.input_data["user"]
        email = user["email"]

        decision_id = ctx.runtime.decide(
            intent="Verify email format",
            options=[
                {"id": "valid", "description": "Email is valid"},
                {"id": "invalid", "description": "Email is invalid"}
            ],
            chosen="valid" if "@" in email else "invalid",
            reasoning=f"Email format check: {email}"
        )

        is_valid = "@" in email

        ctx.runtime.record_outcome(
            decision_id,
            success=is_valid,
            result={"is_valid": is_valid}
        )

        if not is_valid:
            return NodeResult(
                success=False,
                error="Invalid email format"
            )

        return NodeResult(
            success=True,
            output={"verified": True}
        )
```

### Node 3: Send Welcome

```python
class SendWelcomeNode(NodeProtocol):
    """Sends welcome email - like a POST /emails endpoint"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        user = ctx.input_data["user"]

        decision_id = ctx.runtime.decide(
            intent="Send welcome email",
            options=[
                {"id": "send", "description": "Send email"},
                {"id": "skip", "description": "Skip email"}
            ],
            chosen="send",
            reasoning="User verified"
        )

        # Simulate sending email
        email_id = f"email-{user['id']}"

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"email_id": email_id, "sent_to": user["email"]}
        )

        return NodeResult(
            success=True,
            output={"email_sent": True, "email_id": email_id}
        )
```

### Graph Definition

```python
# Like: GET /users/:id → validate → POST /emails

verification_graph = GraphSpec(
    id="user_verification",
    nodes={
        "fetch": NodeSpec(
            id="fetch",
            node_type="function",
            input_keys=["user_id"],
            output_keys=["user"]
        ),
        "verify": NodeSpec(
            id="verify",
            node_type="function",
            input_keys=["user"],
            output_keys=["verified"]
        ),
        "welcome": NodeSpec(
            id="welcome",
            node_type="function",
            input_keys=["user"],
            output_keys=["email_sent"]
        )
    },
    edges={
        "fetch_to_verify": EdgeSpec(
            from_id="fetch",
            to_id="verify"
        ),
        "verify_to_welcome": EdgeSpec(
            from_id="verify",
            to_id="welcome"
        )
    },
    initial_node="fetch",
    terminal_nodes=["welcome"]
)
```

### Execute & Test

```python
executor.register_node("fetch", FetchUserNode())
executor.register_node("verify", VerifyEmailNode())
executor.register_node("welcome", SendWelcomeNode())

# Run with valid user
result = await executor.execute(
    graph=verification_graph,
    goal=Goal(id="verify_user", description="Verify and welcome user"),
    input_data={"user_id": "123"}
)

print(f"Success: {result.success}")
print(f"Email sent: {result.output.get('email_sent')}")
```

### What You Learned

✅ Multi-node graphs  
✅ Data flowing between nodes (shared_memory)  
✅ Error handling (email validation failed)  
✅ Sequential execution  
✅ Multiple run states captured

---

## Project 2: LLM-Powered Node with Routing (2-3 hours)

**Goal**: Use LLM to make decisions + route to different nodes

### Scenario: Customer Support Router

```
User Message → Classify Intent (LLM) → Route to Team
```

### Node 1: Classify Intent

```python
class ClassifyIntentNode(NodeProtocol):
    """Use LLM to classify user message - like ML model in middleware"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        message = ctx.input_data["message"]

        decision_id = ctx.runtime.decide(
            intent="Classify customer support request",
            options=[
                {"id": "billing", "description": "Billing issue"},
                {"id": "technical", "description": "Technical issue"},
                {"id": "general", "description": "General inquiry"}
            ],
            chosen="",  # Will be determined by LLM
            reasoning="Using LLM to classify"
        )

        # Call LLM (via ctx.llm)
        # In real implementation, this would call actual LLM
        response = await ctx.llm.call(
            system="Classify support requests as: billing, technical, or general",
            user=f"Classify: {message}",
            temperature=0.3
        )

        # Parse response
        classification = self._parse_classification(response)

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"classification": classification},
            summary=f"Classified as: {classification}"
        )

        # Next node is determined by this classification (routing)
        return NodeResult(
            success=True,
            output={"classification": classification},
            next_node=f"handle_{classification}"  # Route to specific handler
        )

    def _parse_classification(self, response):
        # Simple parsing - in production, use more robust JSON parsing
        if "billing" in response.lower():
            return "billing"
        elif "technical" in response.lower():
            return "technical"
        else:
            return "general"
```

### Handlers (Router Targets)

```python
class BillingHandlerNode(NodeProtocol):
    """Handle billing issues"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        decision_id = ctx.runtime.decide(
            intent="Handle billing request",
            options=[{"id": "handle", "description": "Route to billing team"}],
            chosen="handle",
            reasoning="Classified as billing"
        )

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"team": "billing"}
        )

        return NodeResult(
            success=True,
            output={"assigned_to": "billing_team"}
        )

class TechnicalHandlerNode(NodeProtocol):
    """Handle technical issues"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Similar implementation
        return NodeResult(
            success=True,
            output={"assigned_to": "technical_team"}
        )

class GeneralHandlerNode(NodeProtocol):
    """Handle general inquiries"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        # Similar implementation
        return NodeResult(
            success=True,
            output={"assigned_to": "general_team"}
        )
```

### Graph with Routing

```python
routing_graph = GraphSpec(
    id="support_router",
    nodes={
        "classify": NodeSpec(
            id="classify",
            node_type="llm_generate",
            input_keys=["message"],
            output_keys=["classification"]
        ),
        "handle_billing": NodeSpec(
            id="handle_billing",
            node_type="function",
            input_keys=["classification"],
            output_keys=["assigned_to"]
        ),
        "handle_technical": NodeSpec(
            id="handle_technical",
            node_type="function",
            input_keys=["classification"],
            output_keys=["assigned_to"]
        ),
        "handle_general": NodeSpec(
            id="handle_general",
            node_type="function",
            input_keys=["classification"],
            output_keys=["assigned_to"]
        )
    },
    edges={
        # Edges with conditions (like if-else)
        "to_billing": EdgeSpec(
            from_id="classify",
            to_id="handle_billing",
            condition=EdgeCondition(
                type="output_equals",
                key="classification",
                value="billing"
            )
        ),
        "to_technical": EdgeSpec(
            from_id="classify",
            to_id="handle_technical",
            condition=EdgeCondition(
                type="output_equals",
                key="classification",
                value="technical"
            )
        ),
        "to_general": EdgeSpec(
            from_id="classify",
            to_id="handle_general",
            condition=EdgeCondition(
                type="output_equals",
                key="classification",
                value="general"
            )
        )
    },
    initial_node="classify",
    terminal_nodes=["handle_billing", "handle_technical", "handle_general"]
)
```

### Test Multiple Scenarios

```python
# Setup
executor = GraphExecutor(runtime, llm=my_llm_provider)
executor.register_node("classify", ClassifyIntentNode())
executor.register_node("handle_billing", BillingHandlerNode())
executor.register_node("handle_technical", TechnicalHandlerNode())
executor.register_node("handle_general", GeneralHandlerNode())

# Test 1: Billing issue
result = await executor.execute(
    graph=routing_graph,
    goal=Goal(id="route_support", description="Route support requests"),
    input_data={"message": "Why was I charged twice?"}
)
print(f"Routed to: {result.output['assigned_to']}")  # billing_team

# Test 2: Technical issue
result = await executor.execute(
    graph=routing_graph,
    goal=Goal(id="route_support", description="Route support requests"),
    input_data={"message": "App keeps crashing"}
)
print(f"Routed to: {result.output['assigned_to']}")  # technical_team

# Test 3: General inquiry
result = await executor.execute(
    graph=routing_graph,
    goal=Goal(id="route_support", description="Route support requests"),
    input_data={"message": "How do I use this feature?"}
)
print(f"Routed to: {result.output['assigned_to']}")  # general_team
```

### What You Learned

✅ LLM integration  
✅ Conditional routing (if-else with edges)  
✅ Dynamic next_node (router behavior)  
✅ Multi-path graphs  
✅ Testing different scenarios

---

## Project 3: Analysis & Self-Improvement (2-3 hours)

**Goal**: Run agent multiple times, analyze patterns, identify improvements

### Step 1: Run Agent Multiple Times

```python
# Simulate 20 runs with different inputs
messages = [
    "Why was I charged twice?",  # billing
    "App crashes on login",  # technical
    "How do I reset password?",  # general
    "Refund request",  # billing
    "Feature not working",  # technical
    # ... repeat various messages
]

run_ids = []
for i, message in enumerate(messages):
    result = await executor.execute(
        graph=routing_graph,
        goal=Goal(id="route_support", description="Route support requests"),
        input_data={"message": message}
    )
    run_ids.append(result.run_id)
    print(f"Run {i+1}: {message} → {result.output['assigned_to']}")
```

### Step 2: Analyze Patterns

```python
from framework.builder import BuilderQuery

query = BuilderQuery(storage_path)

# Find patterns
patterns = query.find_patterns("route_support")

print(f"Total runs: {patterns.run_count}")
print(f"Success rate: {patterns.success_rate:.1%}")
print(f"Common failures: {patterns.common_failures}")
print(f"Problematic nodes: {patterns.problematic_nodes}")

# Example output:
# Total runs: 20
# Success rate: 95.0%
# Common failures: []
# Problematic nodes: [('classify', 0.15)]  # 15% of classifications wrong
```

### Step 3: Get Improvement Suggestions

```python
# Get suggestions for improvement
improvements = query.suggest_improvements("route_support")

for improvement in improvements:
    print(f"Priority: {improvement['priority']}")
    print(f"Type: {improvement['type']}")
    print(f"Target: {improvement['target']}")
    print(f"Reason: {improvement['reason']}")
    print(f"Recommendation: {improvement['recommendation']}")
    print()

# Example output:
# Priority: high
# Type: node_improvement
# Target: classify
# Reason: Node has 15.0% failure rate
# Recommendation: Review and improve node 'classify' - high failure rate suggests prompt or tool issues
```

### Step 4: Manual Improvement (What Builder LLM Does)

```python
# Based on suggestions, improve the node

class ImprovedClassifyIntentNode(NodeProtocol):
    """Improved version based on failure analysis"""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        message = ctx.input_data["message"]

        decision_id = ctx.runtime.decide(
            intent="Classify customer support request",
            options=[
                {"id": "billing", "description": "Billing issue"},
                {"id": "technical", "description": "Technical issue"},
                {"id": "general", "description": "General inquiry"}
            ],
            chosen="",
            reasoning="Using improved LLM prompt"
        )

        # IMPROVED: Better system prompt based on failure analysis
        response = await ctx.llm.call(
            system="""You are an expert at classifying customer support requests.
Categories:
- billing: Payment issues, refunds, charges, subscriptions, invoices
- technical: Software bugs, crashes, errors, connection issues, app problems
- general: Feature questions, how-to questions, account info

Respond with ONLY the category name.""",
            user=f"Classify: {message}",
            temperature=0.1  # More deterministic
        )

        classification = response.strip().lower()

        # IMPROVED: Better validation
        valid_categories = ["billing", "technical", "general"]
        if classification not in valid_categories:
            classification = "general"  # Default fallback

        ctx.runtime.record_outcome(
            decision_id,
            success=True,
            result={"classification": classification},
            summary=f"Classified as: {classification}"
        )

        return NodeResult(
            success=True,
            output={"classification": classification},
            next_node=f"handle_{classification}"
        )
```

### Step 5: Test Improvements

```python
# Register improved node
executor2 = GraphExecutor(runtime2, llm=my_llm_provider)
executor2.register_node("classify", ImprovedClassifyIntentNode())  # NEW
executor2.register_node("handle_billing", BillingHandlerNode())
executor2.register_node("handle_technical", TechnicalHandlerNode())
executor2.register_node("handle_general", GeneralHandlerNode())

# Run same tests again
for i, message in enumerate(messages):
    result = await executor2.execute(
        graph=routing_graph,
        goal=Goal(id="route_support_v2", description="Route support requests (improved)"),
        input_data={"message": message}
    )

# Analyze improvements
query2 = BuilderQuery(storage_path)
patterns_new = query2.find_patterns("route_support_v2")

print(f"Before: {patterns.success_rate:.1%}")
print(f"After: {patterns_new.success_rate:.1%}")
print(f"Improvement: {(patterns_new.success_rate - patterns.success_rate) * 100:.1f}%")
```

### What You Learned

✅ How to run agents multiple times  
✅ How to use BuilderQuery for analysis  
✅ How to identify failure patterns  
✅ How to get improvement suggestions  
✅ How to measure improvements  
✅ **The complete self-improvement loop!**

---

## 🎓 Summary of What You've Built

| Project        | Concept          | Learned                           |
| -------------- | ---------------- | --------------------------------- |
| 0: Hello World | Basic node       | Node protocol, decision recording |
| 1: Pipeline    | Multi-node graph | Data flow, shared memory          |
| 2: Router      | LLM + routing    | Conditional edges, routing logic  |
| 3: Analysis    | Self-improvement | Pattern detection, improvements   |

---

## 🚀 Next Challenge

**Build Your Own**: Customer Sentiment Analyzer

Requirements:

- [ ] Accept customer feedback (input)
- [ ] Use LLM to analyze sentiment
- [ ] Route to appropriate team based on sentiment
- [ ] Run 30+ times with various feedbacks
- [ ] Analyze patterns
- [ ] Improve based on failure patterns

---

## 📚 Reference Code Template

For any new node, use this template:

```python
from framework.graph import NodeProtocol, NodeContext, NodeResult
import time

class MyCustomNode(NodeProtocol):
    """
    Description of what this node does
    (like a route handler docstring)
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Main execution method

        Args:
            ctx: NodeContext with:
                - input_data: dict (from previous node or initial input)
                - runtime: Runtime (for recording decisions)
                - llm: LLMProvider (for calling LLM)
                - tools: list of Tool objects available

        Returns:
            NodeResult with:
                - success: bool
                - output: dict (becomes input to next node)
                - error: str (if failed)
                - tokens_used: int
                - latency_ms: int
                - next_node: str (optional, for routing)
        """

        # 1. Get input
        input_value = ctx.input_data.get("key")

        # 2. Record decision (what we're about to do)
        decision_id = ctx.runtime.decide(
            intent="What are we doing?",
            options=[
                {"id": "option1", "description": "Option 1"},
                {"id": "option2", "description": "Option 2"}
            ],
            chosen="option1",
            reasoning="Why option1"
        )

        # 3. Track time
        start = time.time()

        try:
            # 4. Do the work
            result = await self.do_work(input_value)

            # 5. Calculate latency
            latency_ms = int((time.time() - start) * 1000)

            # 6. Record outcome (what actually happened)
            ctx.runtime.record_outcome(
                decision_id,
                success=True,
                result={"data": result},
                summary="Success message"
            )

            # 7. Return result
            return NodeResult(
                success=True,
                output={"result": result},
                tokens_used=0,  # or actual token count
                latency_ms=latency_ms
                # next_node="specific_node"  # Only if routing
            )

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)

            ctx.runtime.record_outcome(
                decision_id,
                success=False,
                error=str(e),
                summary=f"Failed: {str(e)}"
            )

            return NodeResult(
                success=False,
                error=str(e),
                latency_ms=latency_ms
            )

    async def do_work(self, input_value):
        """Your actual business logic here"""
        # Implement your logic
        pass
```

---

**Now you're ready to build! Start with Project 0. 🚀**
