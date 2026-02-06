---
name: hive-patterns
description: Best practices, patterns, and examples for building goal-driven agents. Includes client-facing interaction, feedback edges, judge patterns, fan-out/fan-in, context management, and anti-patterns.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: reference
  part_of: hive
---

# Building Agents - Patterns & Best Practices

Design patterns, examples, and best practices for building robust goal-driven agents.

**Prerequisites:** Complete agent structure using `hive-create`.

## Practical Example: Hybrid Workflow

How to build a node using both direct file writes and optional MCP validation:

```python
# 1. WRITE TO FILE FIRST (Primary - makes it visible)
node_code = '''
search_node = NodeSpec(
    id="search-web",
    node_type="event_loop",
    input_keys=["query"],
    output_keys=["search_results"],
    system_prompt="Search the web for: {query}. Use web_search, then call set_output to store results.",
    tools=["web_search"],
)
'''

Edit(
    file_path="exports/research_agent/nodes/__init__.py",
    old_string="# Nodes will be added here",
    new_string=node_code
)

# 2. OPTIONALLY VALIDATE WITH MCP (Secondary - bookkeeping)
validation = mcp__agent-builder__test_node(
    node_id="search-web",
    test_input='{"query": "python tutorials"}',
    mock_llm_response='{"search_results": [...mock results...]}'
)
```

**User experience:**

- Immediately sees node in their editor (from step 1)
- Gets validation feedback (from step 2)
- Can edit the file directly if needed

## Multi-Turn Interaction Patterns

For agents needing multi-turn conversations with users, use `client_facing=True` on event_loop nodes.

### Client-Facing Nodes

A client-facing node streams LLM output to the user and blocks for user input between conversational turns. This replaces the old pause/resume pattern.

```python
# Client-facing node with STEP 1/STEP 2 prompt pattern
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Gather requirements from the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=["topic"],
    output_keys=["research_brief"],
    system_prompt="""\
You are an intake specialist.

**STEP 1 — Read and respond (text only, NO tool calls):**
1. Read the topic provided
2. If it's vague, ask 1-2 clarifying questions
3. If it's clear, confirm your understanding

**STEP 2 — After the user confirms, call set_output:**
- set_output("research_brief", "Clear description of what to research")
""",
)

# Internal node runs without user interaction
research_node = NodeSpec(
    id="research",
    name="Research",
    description="Search and analyze sources",
    node_type="event_loop",
    input_keys=["research_brief"],
    output_keys=["findings", "sources"],
    system_prompt="Research the topic using web_search and web_scrape...",
    tools=["web_search", "web_scrape", "load_data", "save_data"],
)
```

**How it works:**

- Client-facing nodes stream LLM text to the user and block for input after each response
- User input is injected via `node.inject_event(text)`
- When the LLM calls `set_output` to produce structured outputs, the judge evaluates and ACCEPTs
- Internal nodes (non-client-facing) run their entire loop without blocking
- `set_output` is a synthetic tool — a turn with only `set_output` calls (no real tools) triggers user input blocking

**STEP 1/STEP 2 pattern:** Always structure client-facing prompts with explicit phases. STEP 1 is text-only conversation. STEP 2 calls `set_output` after user confirmation. This prevents the LLM from calling `set_output` prematurely before the user responds.

### When to Use client_facing

| Scenario                            | client_facing | Why                    |
| ----------------------------------- | :-----------: | ---------------------- |
| Gathering user requirements         |      Yes      | Need user input        |
| Human review/approval checkpoint    |      Yes      | Need human decision    |
| Data processing (scanning, scoring) |      No       | Runs autonomously      |
| Report generation                   |      No       | No user input needed   |
| Final confirmation before action    |      Yes      | Need explicit approval |

> **Legacy Note:** The `pause_nodes` / `entry_points` pattern still works for backward compatibility but `client_facing=True` is preferred for new agents.

## Edge-Based Routing and Feedback Loops

### Conditional Edge Routing

Multiple conditional edges from the same source replace the old `router` node type. Each edge checks a condition on the node's output.

```python
# Node with mutually exclusive outputs
review_node = NodeSpec(
    id="review",
    name="Review",
    node_type="event_loop",
    client_facing=True,
    output_keys=["approved_contacts", "redo_extraction"],
    nullable_output_keys=["approved_contacts", "redo_extraction"],
    max_node_visits=3,
    system_prompt="Present the contact list to the operator. If they approve, call set_output('approved_contacts', ...). If they want changes, call set_output('redo_extraction', 'true').",
)

# Forward edge (positive priority, evaluated first)
EdgeSpec(
    id="review-to-campaign",
    source="review",
    target="campaign-builder",
    condition=EdgeCondition.CONDITIONAL,
    condition_expr="output.get('approved_contacts') is not None",
    priority=1,
)

# Feedback edge (negative priority, evaluated after forward edges)
EdgeSpec(
    id="review-feedback",
    source="review",
    target="extractor",
    condition=EdgeCondition.CONDITIONAL,
    condition_expr="output.get('redo_extraction') is not None",
    priority=-1,
)
```

**Key concepts:**

- `nullable_output_keys`: Lists output keys that may remain unset. The node sets exactly one of the mutually exclusive keys per execution.
- `max_node_visits`: Must be >1 on the feedback target (extractor) so it can re-execute. Default is 1.
- `priority`: Positive = forward edge (evaluated first). Negative = feedback edge. The executor tries forward edges first; if none match, falls back to feedback edges.

### Routing Decision Table

| Pattern                | Old Approach            | New Approach                                  |
| ---------------------- | ----------------------- | --------------------------------------------- |
| Conditional branching  | `router` node           | Conditional edges with `condition_expr`       |
| Binary approve/reject  | `pause_nodes` + resume  | `client_facing=True` + `nullable_output_keys` |
| Loop-back on rejection | Manual entry_points     | Feedback edge with `priority=-1`              |
| Multi-way routing      | Router with routes dict | Multiple conditional edges with priorities    |

## Judge Patterns

**Core Principle: The judge is the SOLE mechanism for acceptance decisions.** Never add ad-hoc framework gating to compensate for LLM behavior. If the LLM calls `set_output` prematurely, fix the system prompt or use a custom judge. Anti-patterns to avoid:

- Output rollback logic
- `_user_has_responded` flags
- Premature set_output rejection
- Interaction protocol injection into system prompts

Judges control when an event_loop node's loop exits. Choose based on validation needs.

### Implicit Judge (Default)

When no judge is configured, the implicit judge ACCEPTs when:

- The LLM finishes its response with no tool calls
- All required output keys have been set via `set_output`

Best for simple nodes where "all outputs set" is sufficient validation.

### SchemaJudge

Validates outputs against a Pydantic model. Use when you need structural validation.

```python
from pydantic import BaseModel

class ScannerOutput(BaseModel):
    github_users: list[dict]  # Must be a list of user objects

class SchemaJudge:
    def __init__(self, output_model: type[BaseModel]):
        self._model = output_model

    async def evaluate(self, context: dict) -> JudgeVerdict:
        missing = context.get("missing_keys", [])
        if missing:
            return JudgeVerdict(
                action="RETRY",
                feedback=f"Missing output keys: {missing}. Use set_output to provide them.",
            )
        try:
            self._model.model_validate(context["output_accumulator"])
            return JudgeVerdict(action="ACCEPT")
        except ValidationError as e:
            return JudgeVerdict(action="RETRY", feedback=str(e))
```

### When to Use Which Judge

| Judge           | Use When                              | Example                |
| --------------- | ------------------------------------- | ---------------------- |
| Implicit (None) | Output keys are sufficient validation | Simple data extraction |
| SchemaJudge     | Need structural validation of outputs | API response parsing   |
| Custom          | Domain-specific validation logic      | Score must be 0.0-1.0  |

## Fan-Out / Fan-In (Parallel Execution)

Multiple ON_SUCCESS edges from the same source trigger parallel execution. All branches run concurrently via `asyncio.gather()`.

```python
# Scanner fans out to Profiler and Scorer in parallel
EdgeSpec(id="scanner-to-profiler", source="scanner", target="profiler",
         condition=EdgeCondition.ON_SUCCESS)
EdgeSpec(id="scanner-to-scorer", source="scanner", target="scorer",
         condition=EdgeCondition.ON_SUCCESS)

# Both fan in to Extractor
EdgeSpec(id="profiler-to-extractor", source="profiler", target="extractor",
         condition=EdgeCondition.ON_SUCCESS)
EdgeSpec(id="scorer-to-extractor", source="scorer", target="extractor",
         condition=EdgeCondition.ON_SUCCESS)
```

**Requirements:**

- Parallel event_loop nodes must have **disjoint output_keys** (no key written by both)
- Only one parallel branch may contain a `client_facing` node
- Fan-in node receives outputs from all completed branches in shared memory

## Context Management Patterns

### Tiered Compaction

EventLoopNode automatically manages context window usage with tiered compaction:

1. **Pruning** — Old tool results replaced with compact placeholders (zero-cost, no LLM call)
2. **Normal compaction** — LLM summarizes older messages
3. **Aggressive compaction** — Keeps only recent messages + summary
4. **Emergency** — Hard reset with tool history preservation

### Spillover Pattern

The framework automatically truncates large tool results and saves full content to a spillover directory. The LLM receives a truncation message with instructions to use `load_data` to read the full result.

For explicit data management, use the data tools (real MCP tools, not synthetic):

```python
# save_data, load_data, list_data_files, serve_file_to_user are real MCP tools
# data_dir is auto-injected by the framework — the LLM never sees it

# Saving large results
save_data(filename="sources.json", data=large_json_string)

# Reading with pagination (line-based offset/limit)
load_data(filename="sources.json", offset=0, limit=50)

# Listing available files
list_data_files()

# Serving a file to the user as a clickable link
serve_file_to_user(filename="report.html", label="Research Report")
```

Add data tools to nodes that handle large tool results:

```python
research_node = NodeSpec(
    ...
    tools=["web_search", "web_scrape", "load_data", "save_data", "list_data_files"],
)
```

`data_dir` is a framework context parameter — auto-injected at call time. `GraphExecutor.execute()` sets it per-execution via `ToolRegistry.set_execution_context(data_dir=...)` (using `contextvars` for concurrency safety), ensuring it matches the session-scoped spillover directory.

## Anti-Patterns

### What NOT to Do

- **Don't rely on `export_graph`** — Write files immediately, not at end
- **Don't hide code in session** — Write to files as components are approved
- **Don't wait to write files** — Agent visible from first step
- **Don't batch everything** — Write incrementally, one component at a time
- **Don't create too many thin nodes** — Prefer fewer, richer nodes (see below)
- **Don't add framework gating for LLM behavior** — Fix prompts or use judges instead

### Fewer, Richer Nodes

A common mistake is splitting work into too many small single-purpose nodes. Each node boundary requires serializing outputs, losing in-context information, and adding edge complexity.

| Bad (8 thin nodes)  | Good (4 rich nodes)                 |
| ------------------- | ----------------------------------- |
| parse-query         | intake (client-facing)              |
| search-sources      | research (search + fetch + analyze) |
| fetch-content       | review (client-facing)              |
| evaluate-sources    | report (write + deliver)            |
| synthesize-findings |                                     |
| write-report        |                                     |
| quality-check       |                                     |
| save-report         |                                     |

**Why fewer nodes are better:**

- The LLM retains full context of its work within a single node
- A research node that searches, fetches, and analyzes keeps all source material in its conversation history
- Fewer edges means simpler graph and fewer failure points
- Data tools (`save_data`/`load_data`) handle context window limits within a single node

### MCP Tools - Correct Usage

**MCP tools OK for:**

- `test_node` — Validate node configuration with mock inputs
- `validate_graph` — Check graph structure
- `configure_loop` — Set event loop parameters
- `create_session` — Track session state for bookkeeping

**Just don't:** Use MCP as the primary construction method or rely on export_graph

## Error Handling Patterns

### Graceful Failure with Fallback

```python
edges = [
    # Success path
    EdgeSpec(id="api-success", source="api-call", target="process-results",
             condition=EdgeCondition.ON_SUCCESS),
    # Fallback on failure
    EdgeSpec(id="api-to-fallback", source="api-call", target="fallback-cache",
             condition=EdgeCondition.ON_FAILURE, priority=1),
    # Report if fallback also fails
    EdgeSpec(id="fallback-to-error", source="fallback-cache", target="report-error",
             condition=EdgeCondition.ON_FAILURE, priority=1),
]
```

## Handoff to Testing

When agent is complete, transition to testing phase:

### Pre-Testing Checklist

- [ ] Agent structure validates: `uv run python -m agent_name validate`
- [ ] All nodes defined in nodes/**init**.py
- [ ] All edges connect valid nodes with correct priorities
- [ ] Feedback edge targets have `max_node_visits > 1`
- [ ] Client-facing nodes have meaningful system prompts
- [ ] Agent can be imported: `from exports.agent_name import default_agent`

## Related Skills

- **hive-concepts** — Fundamental concepts (node types, edges, event loop architecture)
- **hive-create** — Step-by-step building process
- **hive-test** — Test and validate agents
- **hive** — Complete workflow orchestrator

---

**Remember: Agent is actively constructed, visible the whole time. No hidden state. No surprise exports. Just transparent, incremental file building.**
