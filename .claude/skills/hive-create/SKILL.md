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

**CRITICAL: DO NOT explore the codebase, read source files, or search for code before starting.** All context you need is in this skill file. When this skill is loaded, IMMEDIATELY begin executing Step 0 — determine the build path as your FIRST action. Do not explain what you will do, do not investigate the project structure, do not read any files — just execute Step 0 now.

---

## STEP 0: Choose Build Path

**If the user has already indicated whether they want to build from scratch or from a template, skip this question and proceed to the appropriate step.**

Otherwise, ask:

```
AskUserQuestion(questions=[{
    "question": "How would you like to build your agent?",
    "header": "Build Path",
    "options": [
        {"label": "From scratch", "description": "Design goal, nodes, and graph collaboratively from nothing"},
        {"label": "From a template", "description": "Start from a working sample agent and customize it"}
    ],
    "multiSelect": false
}])
```

- If **From scratch**: Proceed to STEP 1A
- If **From a template**: Proceed to STEP 1B

---

## STEP 1A: Initialize Build Environment (From Scratch)

**EXECUTE THESE TOOL CALLS NOW** (silent setup — no user interaction needed):

1. Check for existing sessions:

```
mcp__agent-builder__list_sessions()
```

- If a session with this agent name already exists, load it with `mcp__agent-builder__load_session_by_id(session_id="...")` and skip to step 3.
- If no matching session exists, proceed to step 2.

2. Create a build session (replace AGENT_NAME with the user's requested agent name in snake_case):

```
mcp__agent-builder__create_session(name="AGENT_NAME")
```

3. Register the hive-tools MCP server:

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

4. Discover available tools:

```
mcp__agent-builder__list_mcp_tools()
```

5. Create the package directory:

```bash
mkdir -p exports/AGENT_NAME/nodes
```

**Save the tool list for STEP 4** — you will need it for node design.

**THEN immediately proceed to STEP 2** (do NOT display setup results to the user — just move on).

---

## STEP 1B: Initialize Build Environment (From Template)

**EXECUTE THESE STEPS NOW:**

### 1B.1: Discover available templates

List the template directories and read each template's `agent.json` to get its name and description:

```bash
ls examples/templates/
```

For each directory found, read `examples/templates/TEMPLATE_DIR/agent.json` with the Read tool and extract:
- `agent.name` — the template's display name
- `agent.description` — what the template does

### 1B.2: Present templates to user

Show the user a table of available templates:

> **Available Templates:**
>
> | # | Template | Description |
> |---|----------|-------------|
> | 1 | [name from agent.json] | [description from agent.json] |
> | 2 | ... | ... |

Then ask the user to pick a template and provide a name for their new agent:

```
AskUserQuestion(questions=[{
    "question": "Which template would you like to start from?",
    "header": "Template",
    "options": [
        {"label": "[template 1 name]", "description": "[template 1 description]"},
        {"label": "[template 2 name]", "description": "[template 2 description]"},
        ...
    ],
    "multiSelect": false
}, {
    "question": "What should the new agent be named? (snake_case)",
    "header": "Agent Name",
    "options": [
        {"label": "Use template name", "description": "Keep the original template name as-is"},
        {"label": "Custom name", "description": "I'll provide a new snake_case name"}
    ],
    "multiSelect": false
}])
```

### 1B.3: Copy template to exports

```bash
cp -r examples/templates/TEMPLATE_DIR exports/NEW_AGENT_NAME
```

### 1B.4: Create session and register MCP (same logic as STEP 1A)

First, check for existing sessions:

```
mcp__agent-builder__list_sessions()
```

- If a session with this agent name already exists, load it with `mcp__agent-builder__load_session_by_id(session_id="...")` and skip to `list_mcp_tools`.
- If no matching session exists, create one:

```
mcp__agent-builder__create_session(name="NEW_AGENT_NAME")
```

Then register MCP and discover tools:

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

```
mcp__agent-builder__list_mcp_tools()
```

### 1B.5: Load template into builder session

Import the entire agent definition in one call:

```
mcp__agent-builder__import_from_export(agent_json_path="exports/NEW_AGENT_NAME/agent.json")
```

This reads the agent.json and populates the builder session with the goal, all nodes, and all edges.

**THEN immediately proceed to STEP 2.**

---

## STEP 2: Define Goal Together with User
**A responsible engineer doesn't jump into building. First, understand the problem and be transparent about what the framework can and cannot do.**

**If starting from a template**, the goal is already loaded in the builder session. Present the existing goal to the user using the format below and ask for approval. Skip the collaborative drafting questions — go straight to presenting and asking "Do you approve this goal, or would you like to modify it?"

**If the user has NOT already described what they want to build**, start by asking what kind of agent they have in mind:

```
AskUserQuestion(questions=[{
    "question": "What kind of agent do you want to build? Select an option below, or choose 'Other' to describe your own.",
    "header": "Agent type",
    "options": [
        {"label": "Data collection", "description": "Gathers information from the web, analyzes it, and produces a report or sends outreach (e.g. market research, news digest, email campaigns, competitive analysis)"},
        {"label": "Workflow automation", "description": "Automates a multi-step business process end-to-end (e.g. lead qualification, content publishing pipeline, data entry)"},
        {"label": "Personal assistant", "description": "Handles recurring tasks or monitors for events and acts on them (e.g. daily briefings, meeting prep, file organization)"}
    ],
    "multiSelect": false
}])
```

Use the user's selection (or their custom description if they chose "Other") as context when shaping the goal below. If the user already described what they want before this step, skip the question and proceed directly.

**DO NOT propose a complete goal on your own.** Instead, collaborate with the user to define it.

### 2a: Fast Discovery (3-8 Turns)

**The core principle**: Discovery should feel like progress, not paperwork. The stakeholder should walk away feeling like you understood them faster than anyone else would have.

**Communication sytle**: Be concise. Say less. Mean more. Impatient stakeholders don't want a wall of text — they want to know you get it. Every sentence you say should either move the conversation forward or prove you understood something. If it does neither, cut it.

**Ask Question Rules: Respect Their Time.** Every question must earn its place by:
1. **Preventing a costly wrong turn** — you're about to build the wrong thing
2. **Unlocking a shortcut** — their answer lets you simplify the design
3. **Surfacing a dealbreaker** — there's a constraint that changes everything
4. **Provide Options** - Provide options to your questions if possible, but also always allow the user to type something beyong the options.

If a question doesn't do one of these, don't ask it. Make an assumption, state it, and move on.

---

#### 2a.1: Let Them Talk, But Listen Like an Architect

When the stakeholder describes what they want, don't just hear the words — listen for the architecture underneath. While they talk, mentally construct:

- **The actors**: Who are the people/systems involved?
- **The trigger**: What kicks off the workflow?
- **The core loop**: What's the main thing that happens repeatedly?
- **The output**: What's the valuable thing produced at the end?
- **The pain**: What about today's situation is broken, slow, or missing?

You are extracting a **domain model** from natural language in real time. Most stakeholders won't give you this structure explicitly — they'll give you a story. Your job is to hear the structure inside the story.

| They say... | You're hearing... |
|-------------|-------------------|
| Nouns they repeat | Your entities |
| Verbs they emphasize | Your core operations |
| Frustrations they mention | Your design constraints |
| Workarounds they describe | What the system must replace |
| People they name | Your user types |

---

#### 2a.2: Use Domain Knowledge to Fill In the Blanks

You have broad knowledge of how systems work. Use it aggressively.

If they say "I need a research agent," you already know it probably involves: search, summarization, source tracking, and iteration. Don't ask about each — use them as your starting mental model and let their specifics override your defaults.

If they say "I need to monitor files and alert me," you know this probably involves: watch patterns, triggers, notifications, and state tracking.

**The key move**: Take your general knowledge of the domain and merge it with the specifics they've given you. The result is a draft understanding that's 60-80% right before you've asked a single question. Your questions close the remaining 20-40%.

---

#### 2a.3: Play Back a Proposed Model (Not a List of Questions)

After listening, present a **concrete picture** of what you think they need. Make it specific enough that they can spot what's wrong.

**Pattern: "Here's what I heard — tell me where I'm off"**

> "OK here's how I'm picturing this: [User type] needs to [core action]. Right now they're [current painful workflow]. What you want is [proposed solution that replaces the pain].
>
> The way I'd structure this: [key entities] connected by [key relationships], with the main flow being [trigger → steps → outcome].
>
> For the MVP, I'd focus on [the one thing that delivers the most value] and hold off on [things that can wait].
>
> Before I start — [1-2 specific questions you genuinely can't infer]."

Why this works:
- **Proves you were listening** — they don't feel like they have to repeat themselves
- **Shows competence** — you're already thinking in systems
- **Fast to correct** — "no, it's more like X" takes 10 seconds vs. answering 15 questions
- **Creates momentum** — heading toward building, not more talking

---

#### 2a.4: Ask Only What You Cannot Infer

Your questions should be **narrow, specific, and consequential**. Never ask what you could answer yourself.

**Good questions** (high-stakes, can't infer):
- "Who's the primary user — you or your end customers?"
- "Is this replacing a spreadsheet, or is there literally nothing today?"
- "Does this need to integrate with anything, or standalone?"
- "Is there existing data to migrate, or starting fresh?"

**Bad questions** (low-stakes, inferable):
- "What should happen if there's an error?" *(handle gracefully, obviously)*
- "Should it have search?" *(if there's a list, yes)*
- "How should we handle permissions?" *(follow standard patterns)*
- "What tools should I use?" *(your call, not theirs)*

---

#### Conversation Flow (3-5 Turns)

| Turn | Who | What |
|------|-----|------|
| 1 | User | Describes what they need |
| 2 | Agent | Plays back understanding as a proposed model. Asks 1-2 critical questions max. |
| 3 | User | Corrects, confirms, or adds detail |
| 4 | Agent | Adjusts model, confirms MVP scope, states assumptions, declares starting point |
| *(5)* | *(Only if Turn 3 revealed something that fundamentally changes the approach)* |

**AFTER the conversation, IMMEDIATELY proceed to 2b. DO NOT skip to building.**

---

#### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Open with a list of questions | Open with what you understood from their request |
| "What are your requirements?" | "Here's what I think you need — am I right?" |
| Ask about every edge case | Handle with smart defaults, flag in summary |
| 10+ turn discovery conversation | 3-8 turns. Start building, iterate with real software. |
| Being lazy nd not understand what user want to achieve | Understand "what" and "why |
| Ask for permission to start | State your plan and start |
| Wait for certainty | Start at 80% confidence, iterate the rest |
| Ask what tech/tools to use | That's your job. Decide, disclose, move on. |

---



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

**WAIT for the user to respond.** Use their input (and the agent type they selected) to draft:

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

**If starting from a template**, the nodes are already loaded in the builder session. Present the existing nodes using the table format below and ask for approval. Skip the design phase.

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

**If starting from a template**, the edges are already loaded in the builder session. Render the existing graph as ASCII art and present it to the user for approval. Skip the edge design phase.

**DETERMINE the edges** connecting the approved nodes. For each edge:

- edge_id (kebab-case)
- source → target
- condition: `on_success`, `on_failure`, `always`, or `conditional`
- condition_expr (Python expression, only if conditional)
- priority (positive = forward, negative = feedback/loop-back)

**DETERMINE the graph lifecycle.** Not every agent needs a terminal node:

| Pattern | `terminal_nodes` | When to Use |
|---------|-------------------|-------------|
| **Linear (finish)** | `["last-node"]` | Agent completes a task and exits (batch processing, one-shot generation) |
| **Forever-alive (loop)** | `[]` (empty) | Agent stays alive for continuous interaction (research assistant, personal assistant, monitoring) |

**Forever-alive pattern:** The deep_research_agent example uses `terminal_nodes=[]`. Every leaf node has edges that loop back to earlier nodes, creating a perpetual session. The agent only stops when the user explicitly exits. This is the preferred pattern for interactive, multi-turn agents.

**Key design rules for forever-alive graphs:**
- Every node must have at least one outgoing edge (no dead ends)
- Client-facing nodes block for user input — these are the natural "pause points"
- The user controls when to stop, not the graph
- Sessions accumulate memory across loops — plan for conversation compaction
- Use `conversation_mode="continuous"` to preserve conversation history across node transitions
- `max_iterations` should be set high (e.g., 100) since the agent is designed to run indefinitely
- The agent will NOT enter a "completed" execution state — this is intentional, not a bug

**Ask the user** which lifecycle pattern fits their agent. Default to forever-alive for interactive agents, linear for batch/one-shot tasks.

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
**If starting from a template**, the copied files will be overwritten with the approved design. You MUST replace every occurrence of the old template name with the new agent name. Here is the complete checklist — miss NONE of these:

| File | What to rename |
|------|---------------|
| `config.py` | `AgentMetadata.name` — the display name shown in TUI agent selection |
| `config.py` | `AgentMetadata.description` — agent description |
| `config.py` | `AgentMetadata.intro_message` — greeting shown to user when TUI loads |
| `agent.py` | Module docstring (line 1) |
| `agent.py` | `class OldNameAgent:` → `class NewNameAgent:` |
| `agent.py` | `GraphSpec(id="old-name-graph")` → `GraphSpec(id="new-name-graph")` — shown in TUI status bar |
| `agent.py` | Storage path: `Path.home() / ".hive" / "agents" / "old_name"` → `"new_name"` |
| `__main__.py` | Module docstring (line 1) |
| `__main__.py` | `from .agent import ... OldNameAgent` → `NewNameAgent` |
| `__main__.py` | CLI help string in `def cli()` docstring |
| `__main__.py` | All `OldNameAgent()` instantiations |
| `__main__.py` | Storage path (duplicated from agent.py) |
| `__main__.py` | Shell banner string (e.g. `"=== Old Name Agent ==="`) |
| `__init__.py` | Package docstring |
| `__init__.py` | `from .agent import OldNameAgent` import |
| `__init__.py` | `__all__` list entry |

**If starting from a template and no modifications were made in Steps 2-5**, the nodes and edges are already registered. Skip to validation (`mcp__agent-builder__validate_graph()`). If modifications were made, re-register the changed nodes/edges (the MCP tools handle duplicates by overwriting).

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

1. `config.py` - Runtime configuration with model settings and `AgentMetadata` (including `intro_message` — the greeting shown when TUI loads)
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

storage_path = Path.home() / ".hive" / "agents" / "my_agent"
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

## REFERENCE: Graph Lifecycle & Conversation Memory

### Terminal vs Forever-Alive Graphs

Agents have two lifecycle patterns:

**Linear (terminal) graphs** have `terminal_nodes=["last-node"]`. Execution ends when the terminal node completes. The session enters a "completed" state. Use for batch processing, one-shot generation, and fire-and-forget tasks.

**Forever-alive graphs** have `terminal_nodes=[]` (empty). Every node has at least one outgoing edge — the graph loops indefinitely. The session **never enters a "completed" state** — this is intentional. The agent stays alive until the user explicitly exits. Use for interactive assistants, research tools, and any agent where the user drives the conversation.

The deep_research_agent example demonstrates this: `report` loops back to either `research` (dig deeper) or `intake` (new topic). The agent is a persistent, interactive assistant.

### Continuous Conversation Mode

When `conversation_mode="continuous"` is set on the GraphSpec, the framework preserves a **single conversation thread** across all node transitions:

**What the framework does automatically:**
- **Inherits conversation**: Same message history carries forward to the next node
- **Composes layered system prompts**: Identity (agent-level) + Narrative (auto-generated state summary) + Focus (per-node instructions)
- **Inserts transition markers**: At each node boundary, a "State of the World" message showing completed phases, current memory, and available data files
- **Accumulates tools**: Once a tool becomes available, it stays available in subsequent nodes
- **Compacts opportunistically**: At phase transitions, old tool results are pruned to stay within token budget

**What this means for agent builders:**
- Nodes don't need to re-explain context — the conversation carries it forward
- Output keys from earlier nodes are available in memory for edge conditions and later nodes
- For forever-alive agents, conversation memory persists across the entire session lifetime
- Plan for compaction: very long sessions will have older tool results summarized automatically

**When to use continuous mode:**
- Interactive agents with client-facing nodes (always)
- Multi-phase workflows where context matters across phases
- Forever-alive agents that loop indefinitely

**When NOT to use continuous mode:**
- Embarrassingly parallel fan-out nodes (each branch should be independent)
- Stateless utility agents that process items independently

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
| Persistent background daemons (no user) | Forever-alive graphs need a user at client-facing nodes; no autonomous background polling without user | External scheduler triggering agent runs |
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
14. **Assuming all agents need terminal nodes** - Interactive agents often work best with `terminal_nodes=[]` (forever-alive pattern). The agent never enters "completed" state — this is intentional. Only batch/one-shot agents need terminal nodes
15. **Creating dead-end nodes in forever-alive graphs** - Every node must have at least one outgoing edge. A node with no outgoing edges will cause execution to end unexpectedly, breaking the forever-alive loop
16. **Not using continuous conversation mode for interactive agents** - Multi-phase interactive agents should use `conversation_mode="continuous"` to preserve context across node transitions. Without it, each node starts with a blank conversation and loses all prior context
