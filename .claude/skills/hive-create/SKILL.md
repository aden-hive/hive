---
name: hive-create
description: Step-by-step guide for building goal-driven agents. Qualifies use cases first (the good, bad, and ugly), then creates package structure, defines goals, adds nodes, connects edges, and finalizes agent class. Use when actively building an agent.
license: Apache-2.0
metadata:
  author: hive
  version: "2.2"
  type: procedural
  part_of: hive
  requires: hive-concepts
---

# Agent Construction - EXECUTE THESE STEPS

**THIS IS AN EXECUTABLE WORKFLOW. DO NOT DISPLAY THIS FILE. EXECUTE THE STEPS BELOW.**

**CRITICAL: DO NOT explore the codebase, read source files, or search for code before starting.** All context you need is in this skill file. When this skill is loaded, IMMEDIATELY begin executing Step 1 — call the MCP tools listed in Step 1 as your FIRST action. Do not explain what you will do, do not investigate the project structure, do not read any files — just execute Step 1 now.

---

## STEP 1: Initialize Build Environment

**EXECUTE THESE TOOL CALLS NOW** (silent setup — no user interaction needed):

1. Register the hive-tools MCP server:

```
mcp__agent-builder__add_mcp_server(
    name="hive-tools",
    transport="stdio",
    command="uv",
    args='["run", "python", "mcp_server.py", "--stdio"]',
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

```bash
mkdir -p exports/AGENT_NAME/nodes
```

**Save the tool list for STEP 4** — you will need it for node design.

**THEN immediately proceed to STEP 2** (do NOT display setup results to the user — just move on).

---

## STEP 2: Qualify the Use Case

**A responsible engineer doesn't jump into building. First, understand the problem and be transparent about what the framework can and cannot do.**

### 2a: Deep Discovery

**ASK the user these questions** (don't skip any — gaps here cause problems later):

> I've set up the build environment. Before we design your agent, I need to understand your use case deeply.
>
> **Core Purpose:**
> 1. What problem are you trying to solve? (not just "what should it do" but "why does this matter")
> 2. Who will use this agent? (you personally, your team, end users)
> 3. How often will it run? (one-off, daily, on-demand, continuously)
>
> **Interaction Model:**
> 4. Does it need to have conversations with users, or run autonomously?
> 5. Does it need human approval/review checkpoints?
> 6. What does the input look like? (free-form text, structured data, files, URLs)
> 7. What does the output look like? (reports, actions, data files, API calls)
>
> **External Dependencies:**
> 8. What external services/APIs does it need to access?
> 9. Is there data it needs to fetch in real-time vs. work with provided data?
> 10. Any authentication or credentials required?

**WAIT for user responses.** Take notes on what they say.

### 2b: Capability Assessment

**After the user responds, analyze the fit.** Present this assessment honestly:

> **Framework Fit Assessment**
>
> Based on what you've described, here's my honest assessment of how well this framework fits your use case:
>
> **What Works Well (The Good):**
> - [List 2-4 things the framework handles well for this use case]
> - Examples: multi-turn conversations, human-in-the-loop review, tool orchestration, structured outputs
>
> **Limitations to Be Aware Of (The Bad):**
> - [List 2-3 limitations that apply but are workable]
> - Examples: LLM latency means not suitable for sub-second responses, context window limits for very large documents, cost per run for heavy tool usage
>
> **Potential Deal-Breakers (The Ugly):**
> - [List any significant challenges or missing capabilities — be honest]
> - Examples: no tool available for X, would require custom MCP server, framework not designed for Y

**Be specific.** Reference the actual tools discovered in Step 1. If the user needs `send_email` but it's not available, say so. If they need real-time streaming from a database, explain that's not how the framework works.

### 2c: Gap Analysis

**Identify specific gaps** between what the user wants and what you can deliver:

| Requirement | Framework Support | Gap/Workaround |
|-------------|-------------------|----------------|
| [User need] | [✅ Supported / ⚠️ Partial / ❌ Not supported] | [How to handle or why it's a problem] |

**Examples of gaps to identify:**
- Missing tools (user needs X, but only Y and Z are available)
- Scope issues (user wants to process 10,000 items, but LLM rate limits apply)
- Interaction mismatches (user wants CLI-only, but agent is designed for TUI)
- Data flow issues (user needs to persist state across runs, but sessions are isolated)
- Latency requirements (user needs instant responses, but LLM calls take seconds)

### 2d: Recommendation

**Give a clear recommendation:**

> **My Recommendation:**
>
> [One of these three:]
>
> **✅ PROCEED** — This is a good fit. The framework handles your core needs well. [List any minor caveats.]
>
> **⚠️ PROCEED WITH SCOPE ADJUSTMENT** — This can work, but we should adjust: [specific changes]. Without these adjustments, you'll hit [specific problems].
>
> **🛑 RECONSIDER** — This framework may not be the right tool for this job because [specific reasons]. Consider instead: [alternatives — simpler script, different framework, custom solution].

### 2e: Get Explicit Acknowledgment

**CALL AskUserQuestion:**

```
AskUserQuestion(questions=[{
    "question": "Based on this assessment, how would you like to proceed?",
    "header": "Proceed",
    "options": [
        {"label": "Proceed as described", "description": "I understand the limitations, let's build it"},
        {"label": "Adjust scope", "description": "Let's modify the requirements to fit better"},
        {"label": "More questions", "description": "I have questions about the assessment"},
        {"label": "Reconsider", "description": "Maybe this isn't the right approach"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Proceed**: Move to STEP 3
- If **Adjust scope**: Discuss what to change, update your notes, re-assess if needed
- If **More questions**: Answer them honestly, then ask again
- If **Reconsider**: Discuss alternatives. If they decide to proceed anyway, that's their informed choice

---

## STEP 3: Define Goal Together with User

**Now that the use case is qualified, collaborate on the goal definition.**

**START by synthesizing what you learned:**

> Based on our discussion, here's my understanding of the goal:
>
> **Core purpose:** [what you understood from 2a]
> **Success looks like:** [what you inferred]
> **Key constraints:** [what you inferred]
>
> Let me refine this with you:
>
> 1. **What should this agent accomplish?** (confirm or correct my understanding)
> 2. **How will we know it succeeded?** (what specific outcomes matter)
> 3. **Are there any hard constraints?** (things it must never do, quality bars)

**WAIT for the user to respond.** Use their input to draft:

- Goal ID (kebab-case)
- Goal name
- Goal description
- 3-5 success criteria (each with: id, description, metric, target, weight)
- 2-4 constraints (each with: id, description, constraint_type, category)

**PRESENT the draft goal for approval:**

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
        {"label": "Approve", "description": "Goal looks good, proceed to workflow design"},
        {"label": "Modify", "description": "I want to change something"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Approve**: Call `mcp__agent-builder__set_goal(...)` with the goal details, then proceed to STEP 4
- If **Modify**: Ask what they want to change, update the draft, ask again

---

## STEP 4: Design Conceptual Nodes

**BEFORE designing nodes**, review the available tools from Step 1. Nodes can ONLY use tools that exist.

**DESIGN the workflow** as a series of nodes. For each node, determine:

- node_id (kebab-case)
- name
- description
- node_type: `"event_loop"` (recommended for all LLM work) or `"function"` (deterministic, no LLM)
- input_keys (what data this node receives)
- output_keys (what data this node produces)
- tools (ONLY tools that exist from Step 1 — empty list if no tools needed)
- client_facing: True if this node interacts with the user
- nullable_output_keys (for mutually exclusive outputs or feedback-only inputs)
- max_node_visits (>1 if this node is a feedback loop target)

**Prefer fewer, richer nodes** (4 nodes > 8 thin nodes). Each node boundary requires serializing outputs. A research node that searches, fetches, and analyzes keeps all source material in its conversation history.

**PRESENT the nodes to the user for review:**

> **Proposed Nodes ([N] total):**
>
> | #   | Node ID    | Type       | Description                   | Tools                  | Client-Facing |
> | --- | ---------- | ---------- | ----------------------------- | ---------------------- | :-----------: |
> | 1   | `intake`   | event_loop | Gather requirements from user | —                      |      Yes      |
> | 2   | `research` | event_loop | Search and analyze sources    | web_search, web_scrape |      No       |
> | 3   | `review`   | event_loop | Present findings for approval | —                      |      Yes      |
> | 4   | `report`   | event_loop | Generate final report         | save_data              |      No       |
>
> **Data Flow:**
>
> - `intake` produces: `research_brief`
> - `research` receives: `research_brief` → produces: `findings`, `sources`
> - `review` receives: `findings`, `sources` → produces: `approved_findings` or `feedback`
> - `report` receives: `approved_findings` → produces: `final_report`

**THEN call AskUserQuestion:**

```
AskUserQuestion(questions=[{
    "question": "Do you approve these nodes?",
    "header": "Nodes",
    "options": [
        {"label": "Approve", "description": "Nodes look good, proceed to graph design"},
        {"label": "Modify", "description": "I want to change the nodes"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Approve**: Proceed to STEP 5
- If **Modify**: Ask what they want to change, update design, ask again

---

## STEP 5: Design Full Graph and Review

**DETERMINE the edges** connecting the approved nodes. For each edge:

- edge_id (kebab-case)
- source → target
- condition: `on_success`, `on_failure`, `always`, or `conditional`
- condition_expr (Python expression, only if conditional)
- priority (positive = forward, negative = feedback/loop-back)

**RENDER the complete graph as ASCII art.** Make it large and clear — the user needs to see and understand the full workflow at a glance.

**IMPORTANT: Make the ASCII art BIG and READABLE.** Use a box-and-arrow style with generous spacing. Do NOT make it tiny or compressed. Example format:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AGENT: Research Agent                            │
│                                                                            │
│  Goal: Thoroughly research technical topics and produce verified reports   │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────┐
    │       INTAKE          │
    │  (client-facing)      │
    │                       │
    │  in:  topic           │
    │  out: research_brief  │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │      RESEARCH         │
    │                       │
    │  tools: web_search,   │
    │         web_scrape    │
    │                       │
    │  in:  research_brief  │
    │       [feedback]      │
    │  out: findings,       │
    │       sources         │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │       REVIEW          │
    │  (client-facing)      │
    │                       │
    │  in:  findings,       │
    │       sources         │
    │  out: approved_findings│
    │       OR feedback     │
    └───────┬───────┬───────┘
            │       │
   approved │       │ feedback (priority: -1)
            │       │
            ▼       └──────────────────┐
    ┌───────────────────────┐          │
    │       REPORT          │          │
    │                       │          │
    │  tools: save_data     │          │
    │                       │          │
    │  in:  approved_       │          │
    │       findings        │          │
    │  out: final_report    │          │
    └───────────────────────┘          │
                                       │
            ┌──────────────────────────┘
            │ loops back to RESEARCH
            ▼ (max_node_visits: 3)


    EDGES:
    ──────
    1. intake → research         [on_success, priority: 1]
    2. research → review         [on_success, priority: 1]
    3. review → report           [conditional: approved_findings is not None, priority: 1]
    4. review → research         [conditional: feedback is not None, priority: -1]
```

**PRESENT the graph and edges to the user:**

> Here is the complete workflow graph:
>
> [ASCII art above]
>
> **Edge Summary:**
>
> | #   | Edge              | Condition                                    | Priority |
> | --- | ----------------- | -------------------------------------------- | -------- |
> | 1   | intake → research | on_success                                   | 1        |
> | 2   | research → review | on_success                                   | 1        |
> | 3   | review → report   | conditional: `approved_findings is not None` | 1        |
> | 4   | review → research | conditional: `feedback is not None`          | -1       |

**THEN call AskUserQuestion:**

```
AskUserQuestion(questions=[{
    "question": "Do you approve this workflow graph?",
    "header": "Graph",
    "options": [
        {"label": "Approve", "description": "Graph looks good, proceed to build the agent"},
        {"label": "Modify", "description": "I want to change the graph"}
    ],
    "multiSelect": false
}])
```

**WAIT for user response.**

- If **Approve**: Proceed to STEP 6
- If **Modify**: Ask what they want to change, update the graph, re-render, ask again

---

## STEP 6: Build the Agent

**NOW — and only now — write the actual code.** The user has approved the goal, nodes, and graph.

### 6a: Register nodes and edges with MCP

**FOR EACH approved node**, call:

```
mcp__agent-builder__add_node(
    node_id="...",
    name="...",
    description="...",
    node_type="event_loop",
    input_keys='["key1", "key2"]',
    output_keys='["key1"]',
    tools='["tool1"]',
    system_prompt="...",
    client_facing=True/False,
    nullable_output_keys='["key"]',
    max_node_visits=1
)
```

**FOR EACH approved edge**, call:

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

**VALIDATE the graph:**

```
mcp__agent-builder__validate_graph()
```

- If invalid: Fix the issues and re-validate
- If valid: Continue to 6b

### 6b: Write Python package files

**EXPORT the graph data:**

```
mcp__agent-builder__export_graph()
```

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

**IMPORTANT mcp_servers.json format:**

```json
{
  "hive-tools": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "python", "mcp_server.py", "--stdio"],
    "cwd": "../../tools",
    "description": "Hive tools MCP server"
  }
}
```

- NO `"mcpServers"` wrapper (that's Claude Desktop format, NOT hive format)
- `cwd` MUST be `"../../tools"` (relative from `exports/AGENT_NAME/` to `tools/`)
- `command` MUST be `"uv"` with `"args": ["run", "python", ...]` (NOT bare `"python"` which fails on Mac)

**Use the example agent** at `.claude/skills/hive-create/examples/deep_research_agent/` as a template for file structure and patterns. It demonstrates: STEP 1/STEP 2 prompts, client-facing nodes, feedback loops, nullable_output_keys, and data tools.

**AFTER writing all files, tell the user:**

> Agent package created: `exports/AGENT_NAME/`
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

---

## STEP 7: Verify and Test

**RUN validation:**

```bash
cd /home/timothy/oss/hive && PYTHONPATH=exports uv run python -m AGENT_NAME validate
```

- If valid: Agent is complete!
- If errors: Fix the issues and re-run

**TELL the user the agent is ready** and display the next steps box:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ✅ AGENT BUILD COMPLETE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  NEXT STEPS:                                                                │
│                                                                             │
│  1. SET UP CREDENTIALS (if agent uses tools like web_search, send_email):  │
│                                                                             │
│     /hive-credentials --agent AGENT_NAME                                    │
│                                                                             │
│  2. RUN YOUR AGENT:                                                         │
│                                                                             │
│     hive tui                                                                │
│                                                                             │
│     Then select your agent from the list and press Enter.                   │
│                                                                             │
│  3. DEBUG ANY ISSUES:                                                       │
│                                                                             │
│     /hive-debugger                                                          │
│                                                                             │
│     The debugger monitors runtime logs, identifies retry loops,             │
│     tool failures, and missing outputs, and provides fix recommendations.  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## REFERENCE: Node Types

| Type         | tools param             | Use when                                |
| ------------ | ----------------------- | --------------------------------------- |
| `event_loop` | `'["tool1"]'` or `'[]'` | LLM-powered work with or without tools  |
| `function`   | N/A                     | Deterministic Python operations, no LLM |

---

## REFERENCE: NodeSpec Fields

| Field                  | Default | Description                                                           |
| ---------------------- | ------- | --------------------------------------------------------------------- |
| `client_facing`        | `False` | Streams output to user, blocks for input between turns                |
| `nullable_output_keys` | `[]`    | Output keys that may remain unset (mutually exclusive outputs)        |
| `max_node_visits`      | `1`     | Max executions per run. Set >1 for feedback loop targets. 0=unlimited |

---

## REFERENCE: Edge Conditions & Priority

| Condition     | When edge is followed                 |
| ------------- | ------------------------------------- |
| `on_success`  | Source node completed successfully    |
| `on_failure`  | Source node failed                    |
| `always`      | Always, regardless of success/failure |
| `conditional` | When condition_expr evaluates to True |

**Priority:** Positive = forward edge (evaluated first). Negative = feedback edge (loops back to earlier node). Multiple ON_SUCCESS edges from same source = parallel execution (fan-out).

---

## REFERENCE: System Prompt Best Practice

For **internal** event_loop nodes (not client-facing), instruct the LLM to use `set_output`:

```
Use set_output(key, value) to store your results. For example:
- set_output("search_results", <your results as a JSON string>)

Do NOT return raw JSON. Use the set_output tool to produce outputs.
```

For **client-facing** event_loop nodes, use the STEP 1/STEP 2 pattern:

```
**STEP 1 — Respond to the user (text only, NO tool calls):**
[Present information, ask questions, etc.]

**STEP 2 — After the user responds, call set_output:**
- set_output("key", "value based on user's response")
```

This prevents the LLM from calling `set_output` before the user has had a chance to respond. The "NO tool calls" instruction in STEP 1 ensures the node blocks for user input before proceeding.

---

## EventLoopNode Runtime

EventLoopNodes are **auto-created** by `GraphExecutor` at runtime. Both direct `GraphExecutor` and `AgentRuntime` / `create_agent_runtime()` handle event_loop nodes automatically. No manual `node_registry` setup is needed.

```python
# Direct execution
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime

storage_path = Path.home() / ".hive" / "my_agent"
storage_path.mkdir(parents=True, exist_ok=True)
runtime = Runtime(storage_path)

executor = GraphExecutor(
    runtime=runtime,
    llm=llm,
    tools=tools,
    tool_executor=tool_executor,
    storage_path=storage_path,
)
result = await executor.execute(graph=graph, goal=goal, input_data=input_data)
```

**DO NOT pass `runtime=None` to `GraphExecutor`** — it will crash with `'NoneType' object has no attribute 'start_run'`.

---

## REFERENCE: Framework Capabilities for Qualification

Use this reference during STEP 2 to give accurate, honest assessments.

### What the Framework Does Well (The Good)

| Capability | Description |
|------------|-------------|
| Multi-turn conversations | Client-facing nodes stream to users and block for input |
| Human-in-the-loop review | Approval checkpoints with feedback loops back to earlier nodes |
| Tool orchestration | LLM can call multiple tools, framework handles execution |
| Structured outputs | `set_output` produces validated, typed outputs |
| Parallel execution | Fan-out/fan-in for concurrent node execution |
| Context management | Automatic compaction and spillover for large data |
| Error recovery | Retry logic, judges, and feedback edges for self-correction |
| Session persistence | State saved to disk, resumable sessions |

### Framework Limitations (The Bad)

| Limitation | Impact | Workaround |
|------------|--------|------------|
| LLM latency | 2-10+ seconds per turn | Not suitable for real-time/low-latency needs |
| Context window limits | ~128K tokens max | Use data tools for spillover, design for chunking |
| Cost per run | LLM API calls cost money | Budget planning, caching where possible |
| Rate limits | API throttling on heavy usage | Backoff, queue management |
| Node boundaries lose context | Outputs must be serialized | Prefer fewer, richer nodes |
| Single-threaded within node | One LLM call at a time per node | Use fan-out for parallelism |

### Not Designed For (The Ugly)

| Use Case | Why It's Problematic | Alternative |
|----------|---------------------|-------------|
| Long-running daemons | Framework is request-response, not persistent | External scheduler + agent |
| Sub-second responses | LLM latency is inherent | Traditional code, no LLM |
| Processing millions of items | Context windows and rate limits | Batch processing + sampling |
| Real-time streaming data | No built-in pub/sub or streaming input | Custom MCP server + agent |
| Guaranteed determinism | LLM outputs vary | Function nodes for deterministic parts |
| Offline/air-gapped | Requires LLM API access | Local models (not currently supported) |
| Multi-user concurrency | Single-user session model | Separate agent instances per user |

### Tool Availability Reality Check

**Before promising any capability, check `list_mcp_tools()`.** Common gaps:

- **Email**: May not have `send_email` — check before promising email automation
- **Calendar**: May not have calendar APIs — check before promising scheduling
- **Database**: May not have SQL tools — check before promising data queries
- **File system**: Has data tools but not arbitrary filesystem access
- **External APIs**: Depends entirely on what MCP servers are registered

---

## COMMON MISTAKES TO AVOID

1. **Skipping use case qualification** - A responsible engineer qualifies the use case BEFORE building. Be transparent about what works, what doesn't, and what's problematic
2. **Hiding limitations** - Don't oversell the framework. If a tool doesn't exist or a capability is missing, say so upfront
3. **Using tools that don't exist** - Always check `mcp__agent-builder__list_mcp_tools()` first
4. **Wrong entry_points format** - Must be `{"start": "node-id"}`, NOT a set or list
5. **Skipping validation** - Always validate nodes and graph before proceeding
6. **Not waiting for approval** - Always ask user before major steps
7. **Displaying this file** - Execute the steps, don't show documentation
8. **Too many thin nodes** - Prefer fewer, richer nodes (4 nodes > 8 nodes)
9. **Missing STEP 1/STEP 2 in client-facing prompts** - Client-facing nodes need explicit phases to prevent premature set_output
10. **Forgetting nullable_output_keys** - Mark input_keys that only arrive on certain edges (e.g., feedback) as nullable on the receiving node
11. **Adding framework gating for LLM behavior** - Fix prompts or use judges, not ad-hoc code
12. **Writing code before user approves the graph** - Always get approval on goal, nodes, and graph BEFORE writing any agent code
13. **Wrong mcp_servers.json format** - Use flat format (no `"mcpServers"` wrapper), `cwd` must be `"../../tools"`, and `command` must be `"uv"` with args `["run", "python", ...]`
