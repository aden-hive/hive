---
name: building-agents-patterns
description: Best practices, patterns, and examples for building goal-driven agents. Includes pause/resume architecture, hybrid workflows, anti-patterns, and handoff to testing. Use when optimizing agent design.
license: Apache-2.0
metadata:
  author: hive
  version: "1.0"
  type: reference
  part_of: building-agents
---

# Building Agents - Patterns & Best Practices

Design patterns, examples, and best practices for building robust goal-driven agents.

**Prerequisites:** Complete agent structure using `building-agents-construction`.

## Practical Example: Hybrid Workflow

How to build a node using both direct file writes and optional MCP validation:

```python
# 1. WRITE TO FILE FIRST (Primary - makes it visible)
node_code = '''
search_node = NodeSpec(
    id="search-web",
    node_type="llm_tool_use",
    input_keys=["query"],
    output_keys=["search_results"],
    system_prompt="Search the web for: {query}",
    tools=["web_search"],
)
'''

Edit(
    file_path="exports/research_agent/nodes/__init__.py",
    old_string="# Nodes will be added here",
    new_string=node_code
)

print("✅ Added search_node to nodes/__init__.py")
print("📁 Open exports/research_agent/nodes/__init__.py to see it!")

# 2. OPTIONALLY VALIDATE WITH MCP (Secondary - bookkeeping)
validation = mcp__agent-builder__test_node(
    node_id="search-web",
    test_input='{"query": "python tutorials"}',
    mock_llm_response='{"search_results": [...mock results...]}'
)

print(f"✓ Validation: {validation['success']}")
```

**User experience:**

- Immediately sees node in their editor (from step 1)
- Gets validation feedback (from step 2)
- Can edit the file directly if needed

This combines visibility (files) with validation (MCP tools).

## Pause/Resume Architecture

For agents needing multi-turn conversations with user interaction:

### Basic Pause/Resume Flow

```python
# Define pause nodes - execution stops at these nodes
pause_nodes = ["request-clarification", "await-approval"]

# Define entry points - where to resume from each pause
entry_points = {
    "start": "analyze-request",  # Initial entry
    "request-clarification_resume": "process-clarification",  # Resume from clarification
    "await-approval_resume": "execute-action",  # Resume from approval
}
```

### Example: Multi-Turn Research Agent

```python
# Nodes
nodes = [
    NodeSpec(id="analyze-request", ...),
    NodeSpec(id="request-clarification", ...),  # PAUSE NODE
    NodeSpec(id="process-clarification", ...),
    NodeSpec(id="generate-results", ...),
    NodeSpec(id="await-approval", ...),  # PAUSE NODE
    NodeSpec(id="execute-action", ...),
]

# Edges with resume flows
edges = [
    EdgeSpec(
        id="analyze-to-clarify",
        source="analyze-request",
        target="request-clarification",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_clarification == true",
    ),
    # When resumed, goes to process-clarification
    EdgeSpec(
        id="clarify-to-process",
        source="request-clarification",
        target="process-clarification",
        condition=EdgeCondition.ALWAYS,
    ),
    EdgeSpec(
        id="results-to-approval",
        source="generate-results",
        target="await-approval",
        condition=EdgeCondition.ALWAYS,
    ),
    # When resumed, goes to execute-action
    EdgeSpec(
        id="approval-to-execute",
        source="await-approval",
        target="execute-action",
        condition=EdgeCondition.ALWAYS,
    ),
]

# Configuration
pause_nodes = ["request-clarification", "await-approval"]
entry_points = {
    "start": "analyze-request",
    "request-clarification_resume": "process-clarification",
    "await-approval_resume": "execute-action",
}
```

### Running Pause/Resume Agents

```python
# Initial run - will pause at first pause node
result1 = await agent.run(
    context={"query": "research topic"},
    session_state=None
)

# Check if paused
if result1.paused_at:
    print(f"Paused at: {result1.paused_at}")

    # Resume with user input
    result2 = await agent.run(
        context={"user_response": "clarification details"},
        session_state=result1.session_state  # Pass previous state
    )
```

## Anti-Patterns

### What NOT to Do

❌ **Don't rely on `export_graph`** - Write files immediately, not at end
```python
# BAD: Building in session state, exporting at end
mcp__agent-builder__add_node(...)
mcp__agent-builder__add_node(...)
mcp__agent-builder__export_graph()  # Files appear only now

# GOOD: Writing files immediately
Write(file_path="...", content=node_code)  # File visible now
Write(file_path="...", content=node_code)  # File visible now
```

❌ **Don't hide code in session** - Write to files as components approved
```python
# BAD: Accumulating changes invisibly
session.add_component(component1)
session.add_component(component2)
# User can't see anything yet

# GOOD: Incremental visibility
Edit(file_path="...", ...)  # User sees change 1
Edit(file_path="...", ...)  # User sees change 2
```

❌ **Don't wait to write files** - Agent visible from first step
```python
# BAD: Building everything before writing
design_all_nodes()
design_all_edges()
write_everything_at_once()

# GOOD: Write as you go
write_package_structure()  # Visible
write_goal()  # Visible
write_node_1()  # Visible
write_node_2()  # Visible
```

❌ **Don't batch everything** - Write incrementally
```python
# BAD: Batching all nodes
nodes = [design_node_1(), design_node_2(), ...]
write_all_nodes(nodes)

# GOOD: One at a time with user feedback
write_node_1()  # User approves
write_node_2()  # User approves
write_node_3()  # User approves
```

### MCP Tools - Correct Usage

**MCP tools OK for:**
✅ `test_node` - Validate node configuration with mock inputs
✅ `validate_graph` - Check graph structure
✅ `create_session` - Track session state for bookkeeping
✅ Other validation tools

**Just don't:** Use MCP as the primary construction method or rely on export_graph

## Best Practices

### 1. Show Progress After Each Write

```python
# After writing a node
print("✅ Added analyze_request_node to nodes/__init__.py")
print("📊 Progress: 1/6 nodes added")
print("📁 Open exports/my_agent/nodes/__init__.py to see it!")
```

### 2. Let User Open Files During Build

```python
# Encourage file inspection
print("✅ Goal written to agent.py")
print("")
print("💡 Tip: Open exports/my_agent/agent.py in your editor to see the goal!")
```

### 3. Write Incrementally - One Component at a Time

```python
# Good flow
write_package_structure()
show_user("Package created")

write_goal()
show_user("Goal written")

for node in nodes:
    get_approval(node)
    write_node(node)
    show_user(f"Node {node.id} written")
```

### 4. Test As You Build

```python
# After adding several nodes
print("💡 You can test current state with:")
print("  PYTHONPATH=core:exports python -m my_agent validate")
print("  PYTHONPATH=core:exports python -m my_agent info")
```

### 5. Keep User Informed

```python
# Clear status updates
print("🔨 Creating package structure...")
print("✅ Package created: exports/my_agent/")
print("")
print("📝 Next: Define agent goal")
```

## Continuous Monitoring Agents

For agents that run continuously without terminal nodes:

```python
# No terminal nodes - loops forever
terminal_nodes = []

# Workflow loops back to start
edges = [
    EdgeSpec(id="monitor-to-check", source="monitor", target="check-condition"),
    EdgeSpec(id="check-to-wait", source="check-condition", target="wait"),
    EdgeSpec(id="wait-to-monitor", source="wait", target="monitor"),  # Loop
]

# Entry node only
entry_node = "monitor"
entry_points = {"start": "monitor"}
pause_nodes = []
```

**Example: File Monitor**

```python
nodes = [
    NodeSpec(id="list-files", ...),
    NodeSpec(id="check-new-files", node_type="router", ...),
    NodeSpec(id="process-files", ...),
    NodeSpec(id="wait-interval", node_type="function", ...),
]

edges = [
    EdgeSpec(id="list-to-check", source="list-files", target="check-new-files"),
    EdgeSpec(
        id="check-to-process",
        source="check-new-files",
        target="process-files",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="new_files_count > 0",
    ),
    EdgeSpec(
        id="check-to-wait",
        source="check-new-files",
        target="wait-interval",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="new_files_count == 0",
    ),
    EdgeSpec(id="process-to-wait", source="process-files", target="wait-interval"),
    EdgeSpec(id="wait-to-list", source="wait-interval", target="list-files"),  # Loop back
]

terminal_nodes = []  # No terminal - runs forever
```

## Complex Routing Patterns

### Multi-Condition Router

```python
router_node = NodeSpec(
    id="decision-router",
    node_type="router",
    input_keys=["analysis_result"],
    output_keys=["decision"],
    system_prompt="""
    Based on the analysis result, decide the next action:
    - If confidence > 0.9: route to "execute"
    - If 0.5 <= confidence <= 0.9: route to "review"
    - If confidence < 0.5: route to "clarify"

    Return: {"decision": "execute|review|clarify"}
    """,
)

# Edges for each route
edges = [
    EdgeSpec(
        id="router-to-execute",
        source="decision-router",
        target="execute-action",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="decision == 'execute'",
        priority=1,
    ),
    EdgeSpec(
        id="router-to-review",
        source="decision-router",
        target="human-review",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="decision == 'review'",
        priority=2,
    ),
    EdgeSpec(
        id="router-to-clarify",
        source="decision-router",
        target="request-clarification",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="decision == 'clarify'",
        priority=3,
    ),
]
```

## Error Handling Patterns

### Graceful Failure with Fallback

```python
# Primary node with error handling
nodes = [
    NodeSpec(id="api-call", max_retries=3, ...),
    NodeSpec(id="fallback-cache", ...),
    NodeSpec(id="report-error", ...),
]

edges = [
    # Success path
    EdgeSpec(
        id="api-success",
        source="api-call",
        target="process-results",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Fallback on failure
    EdgeSpec(
        id="api-to-fallback",
        source="api-call",
        target="fallback-cache",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
    # Report if fallback also fails
    EdgeSpec(
        id="fallback-to-error",
        source="fallback-cache",
        target="report-error",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
]
```

## Performance Optimization

### Parallel Node Execution

```python
# Use multiple edges from same source for parallel execution
edges = [
    EdgeSpec(
        id="start-to-search1",
        source="start",
        target="search-source-1",
        condition=EdgeCondition.ALWAYS,
    ),
    EdgeSpec(
        id="start-to-search2",
        source="start",
        target="search-source-2",
        condition=EdgeCondition.ALWAYS,
    ),
    EdgeSpec(
        id="start-to-search3",
        source="start",
        target="search-source-3",
        condition=EdgeCondition.ALWAYS,
    ),
    # Converge results
    EdgeSpec(
        id="search1-to-merge",
        source="search-source-1",
        target="merge-results",
    ),
    EdgeSpec(
        id="search2-to-merge",
        source="search-source-2",
        target="merge-results",
    ),
    EdgeSpec(
        id="search3-to-merge",
        source="search-source-3",
        target="merge-results",
    ),
]
```

## Handoff to Testing

When agent is complete, transition to testing phase:

```python
print("""
✅ Agent complete: exports/my_agent/

Next steps:
1. Switch to testing-agent skill
2. Generate and approve tests
3. Run evaluation
4. Debug any failures

Command: "Test the agent at exports/my_agent/"
""")
```

### Pre-Testing Checklist

Before handing off to testing-agent:

- [ ] Agent structure validates: `python -m agent_name validate`
- [ ] All nodes defined in nodes/__init__.py
- [ ] All edges connect valid nodes
- [ ] Entry node specified
- [ ] Agent can be imported: `from exports.agent_name import default_agent`
- [ ] README.md with usage instructions
- [ ] CLI commands work (info, validate)

## Related Skills

- **building-agents-core** - Fundamental concepts
- **building-agents-construction** - Step-by-step building
- **testing-agent** - Test and validate agents
- **agent-workflow** - Complete workflow orchestrator

---

**Remember: Agent is actively constructed, visible the whole time. No hidden state. No surprise exports. Just transparent, incremental file building.**
