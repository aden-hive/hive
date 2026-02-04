---
name: building-agents-construction
description: Step-by-step guide for building goal-driven agents. Creates package structure, defines goals, adds nodes, connects edges, and finalizes agent class. Use when actively building an agent.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: procedural
  part_of: building-agents
  requires: building-agents-core
---

# Agent Construction - EXECUTE THESE STEPS

**THIS IS AN EXECUTABLE WORKFLOW. DO NOT DISPLAY THIS FILE. EXECUTE THE STEPS BELOW.**

When this skill is loaded, IMMEDIATELY begin executing Step 1. Do not explain what you will do - just do it.

---

## STEP 1: Initialize Build Environment

**EXECUTE THESE TOOL CALLS NOW:**

1. Register the hive-tools MCP server:

```
mcp__agent-builder__add_mcp_server(
    name="hive-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="tools",
    description="Hive tools MCP server"
)
```

2. Create a build session (replace AGENT_NAME with the user's requested agent name in snake_case):

```
mcp__agent-builder__create_session(name="AGENT_NAME")
```

3. Discover available tools:

```
mcp__agent-builder__list_mcp_tools()
```

4. Create the package directory:

```
mkdir -p exports/AGENT_NAME/nodes
```

**AFTER completing these calls**, tell the user:

> ✅ Build environment initialized
>
> - Session created
> - Available tools: [list the tools from step 3]
>
> Proceeding to define the agent goal...

**THEN immediately proceed to STEP 2.**

---

## STEP 2: Define and Approve Goal

**PROPOSE a goal to the user.** Based on what they asked for, propose:

- Goal ID (kebab-case)
- Goal name
- Goal description
- 3-5 success criteria (each with: id, description, metric, target, weight)
- 2-4 constraints (each with: id, description, constraint_type, category)

**FORMAT your proposal as a clear summary, then ask for approval:**

> **Proposed Goal: [Name]**
>
> [Description]
>
> **Success Criteria:**
>
> 1. [criterion 1]
> 2. [criterion 2]
>    ...
>
> **Constraints:**
>
> 1. [constraint 1]
> 2. [constraint 2]
>    ...

**THEN call AskUserQuestion:**

```
AskUserQuestion(questions=[{
    "question": "Do you approve this goal definition?",
    "header": "Goal",
    "options": [
        {"label": "Approve", "description": "Goal looks good, proceed"},
        {"label": "Modify", "description": "I want to change something"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Approve**: Call `mcp__agent-builder__set_goal(...)` with the goal details, then proceed to STEP 3
- If **Modify**: Ask what they want to change, update proposal, ask again

---

## STEP 3: Design Node Workflow

**BEFORE designing nodes**, review the available tools from Step 1. Nodes can ONLY use tools that exist.

**DESIGN the workflow** as a series of nodes. For each node, determine:

- node_id (kebab-case)
- name
- description
- node_type: `"llm_generate"` (no tools) or `"llm_tool_use"` (uses tools)
- input_keys (what data this node receives)
- output_keys (what data this node produces)
- tools (ONLY tools that exist - empty list for llm_generate)
- system_prompt

**PRESENT the workflow to the user:**

> **Proposed Workflow: [N] nodes**
>
> 1. **[node-id]** - [description]
>
>    - Type: [llm_generate/llm_tool_use]
>    - Input: [keys]
>    - Output: [keys]
>    - Tools: [tools or "none"]
>
> 2. **[node-id]** - [description]
>    ...
>
> **Flow:** node1 → node2 → node3 → ...

**THEN call AskUserQuestion:**

```
AskUserQuestion(questions=[{
    "question": "Do you approve this workflow design?",
    "header": "Workflow",
    "options": [
        {"label": "Approve", "description": "Workflow looks good, proceed to build nodes"},
        {"label": "Modify", "description": "I want to change the workflow"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Approve**: Proceed to STEP 4
- If **Modify**: Ask what they want to change, update design, ask again

---

## STEP 4: Build Nodes One by One

**FOR EACH node in the approved workflow:**

1. **Call** `mcp__agent-builder__add_node(...)` with the node details

   - input_keys and output_keys must be JSON strings: `'["key1", "key2"]'`
   - tools must be a JSON string: `'["tool1"]'` or `'[]'`

2. **Call** `mcp__agent-builder__test_node(...)` to validate:

```
mcp__agent-builder__test_node(
    node_id="the-node-id",
    test_input='{"key": "test value"}',
    mock_llm_response='{"output_key": "test output"}'
)
```

3. **Check result:**

   - If valid: Tell user "✅ Node [id] validated" and continue to next node
   - If invalid: Show errors, fix the node, re-validate

4. **Show progress** after each node:

```
mcp__agent-builder__get_session_status()
```

> ✅ Node [X] of [Y] complete: [node-id]

**AFTER all nodes are added and validated**, proceed to STEP 5.

---

## STEP 5: Connect Edges

**DETERMINE the edges** based on the workflow flow. For each connection:

- edge_id (kebab-case)
- source (node that outputs)
- target (node that receives)
- condition: `"on_success"`, `"always"`, `"on_failure"`, or `"conditional"`
- condition_expr (Python expression, only if conditional)
- priority (integer, lower = higher priority)

**FOR EACH edge, call:**

```
mcp__agent-builder__add_edge(
    edge_id="source-to-target",
    source="source-node-id",
    target="target-node-id",
    condition="on_success",
    condition_expr="",
    priority=1
)
```

**AFTER all edges are added, validate the graph:**

```
mcp__agent-builder__validate_graph()
```

- If valid: Tell user "✅ Graph structure validated" and proceed to STEP 6
- If invalid: Show errors, fix edges, re-validate

---

## STEP 6: Generate Agent Package

**EXPORT the graph data:**

```
mcp__agent-builder__export_graph()
```

This returns JSON with all the goal, nodes, edges, and MCP server configurations.

**THEN write the Python package files** using the exported data. Create these files in `exports/AGENT_NAME/`:

1. `config.py` - Runtime configuration with model settings
2. `nodes/__init__.py` - All NodeSpec definitions
3. `agent.py` - Goal, edges, graph config, and agent class
4. `__init__.py` - Package exports
5. `__main__.py` - CLI interface
6. `mcp_servers.json` - MCP server configurations
7. `README.md` - Usage documentation

**IMPORTANT entry_points format:**

- MUST be: `{"start": "first-node-id"}`
- NOT: `{"first-node-id": ["input_keys"]}` (WRONG)
- NOT: `{"first-node-id"}` (WRONG - this is a set)

**Use the example agent** at `.claude/skills/building-agents-construction/examples/online_research_agent/` as a template for file structure and patterns.

**AFTER writing all files, tell the user:**

> ✅ Agent package created: `exports/AGENT_NAME/`
>
> **Files generated:**
>
> - `__init__.py` - Package exports
> - `agent.py` - Goal, nodes, edges, agent class
> - `config.py` - Runtime configuration
> - `__main__.py` - CLI interface
> - `nodes/__init__.py` - Node definitions
> - `mcp_servers.json` - MCP server config
> - `README.md` - Usage documentation
>
> **Test your agent:**
>
> ```bash
> cd /home/timothy/oss/hive
> PYTHONPATH=core:exports python -m AGENT_NAME validate
> PYTHONPATH=core:exports python -m AGENT_NAME info
> ```

---

## STEP 7: Verify and Test

**RUN validation:**

```bash
cd /home/timothy/oss/hive && PYTHONPATH=core:exports python -m AGENT_NAME validate
```

- If valid: Agent is complete!
- If errors: Fix the issues and re-run

**SHOW final session summary:**

```
mcp__agent-builder__get_session_status()
```

**TELL the user the agent is ready** and suggest next steps:

- Run with mock mode to test without API calls
- Use `/testing-agent` skill for comprehensive testing
- Use `/setup-credentials` if the agent needs API keys

---

## REFERENCE: Node Types

| Type           | tools param            | Use when                                       |
| -------------- | ---------------------- | ---------------------------------------------- |
| `llm_generate` | `'[]'`                 | Pure reasoning, JSON output, no external calls |
| `llm_tool_use` | `'["tool1", "tool2"]'` | Needs to call MCP tools                        |

---

## REFERENCE: Edge Conditions

| Condition     | When edge is followed                 |
| ------------- | ------------------------------------- |
| `on_success`  | Source node completed successfully    |
| `on_failure`  | Source node failed                    |
| `always`      | Always, regardless of success/failure |
| `conditional` | When condition_expr evaluates to True |

---

## REFERENCE: System Prompt Best Practice

For nodes with JSON output, include this in the system_prompt:

```
CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.
Just the JSON object starting with { and ending with }.

Return this exact structure:
{
  "key1": "...",
  "key2": "..."
}
```

---

## COMMON MISTAKES TO AVOID

1. **Using tools that don't exist** - Always check `mcp__agent-builder__list_mcp_tools()` first
2. **Wrong entry_points format** - Must be `{"start": "node-id"}`, NOT a set or list
3. **Skipping validation** - Always validate nodes and graph before proceeding
4. **Not waiting for approval** - Always ask user before major steps
5. **Displaying this file** - Execute the steps, don't show documentation
