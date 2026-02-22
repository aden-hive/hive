---
name: hive-debugger
type: utility
description: Interactive debugging companion for Hive agents - identifies runtime issues and proposes solutions
version: 1.0.0
requires:
  - hive-concepts
tags:
  - debugging
  - runtime-logs
  - agent-development
---

# Hive Debugger

An interactive debugging companion that helps developers identify and fix runtime issues in Hive agents. The debugger analyzes runtime logs at three levels (L1/L2/L3), categorizes issues, and provides actionable fix recommendations.

## When to Use This Skill

Use `/hive-debugger` when:
- Your agent is failing or producing unexpected results
- You need to understand why a specific node is retrying repeatedly
- Tool calls are failing and you need to identify the root cause
- Agent execution is stalled or taking too long
- You want to monitor agent behavior in real-time during development

This skill works alongside agents running in TUI mode and provides supervisor-level insights into execution behavior.

### Forever-Alive Agent Awareness

Some agents use `terminal_nodes=[]` (the "forever-alive" pattern), meaning they loop indefinitely and never enter a "completed" execution state. For these agents:
- Sessions with status "in_progress" or "paused" are **normal**, not failures
- High step counts, long durations, and many node visits are expected behavior
- The agent stops only when the user explicitly exits — there is no graph-driven completion
- Debug focus should be on **quality of individual node visits and iterations**, not whether the session reached a terminal state
- Conversation memory accumulates across loops — watch for context overflow and stale data issues

**How to identify forever-alive agents:** Check `agent.py` or `agent.json` for `terminal_nodes=[]` (empty list). If empty, the agent is forever-alive.

---

## Prerequisites

Before using this skill, ensure:
1. You have an exported agent in `exports/{agent_name}/`
2. The agent has been run at least once (logs exist)
3. Runtime logging is enabled (default in Hive framework)
4. You have access to the agent's working directory at `~/.hive/agents/{agent_name}/`

---

## Workflow

### Stage 1: Setup & Context Gathering

**Objective:** Understand the agent being debugged

**What to do:**

1. **Ask the developer which agent needs debugging:**
   - Get agent name (e.g., "deep_research_agent", "deep_research_agent")
   - Confirm the agent exists in `exports/{agent_name}/`

2. **Determine agent working directory:**
   - Calculate: `~/.hive/agents/{agent_name}/`
   - Verify this directory exists and contains session logs

3. **Read agent configuration:**
   - Read file: `exports/{agent_name}/agent.json`
   - Extract goal information from the JSON:
     - `goal.id` - The goal identifier
     - `goal.success_criteria` - What success looks like
     - `goal.constraints` - Rules the agent must follow
   - Extract graph information:
     - List of node IDs from `graph.nodes`
     - List of edges from `graph.edges`

4. **Store context for the debugging session:**
   - agent_name
   - agent_work_dir (e.g., `/home/user/.hive/deep_research_agent`)
   - goal_id
   - success_criteria
   - constraints
   - node_ids

**Example:**
```
Developer: "My deep_research_agent agent keeps failing"

You: "I'll help debug the deep_research_agent agent. Let me gather context..."

[Read exports/deep_research_agent/agent.json]

Context gathered:
- Agent: deep_research_agent
- Goal: deep-research
- Working Directory: /home/user/.hive/deep_research_agent
- Success Criteria: ["Produce a comprehensive research report with cited sources"]
- Constraints: ["Must cite all sources", "Must cover multiple perspectives"]
- Nodes: ["intake", "research", "analysis", "report-writer"]
```

---

### Stage 2: Mode Selection

**Objective:** Choose the debugging approach that best fits the situation

**What to do:**

Ask the developer which debugging mode they want to use. Use AskUserQuestion with these options:

1. **Real-time Monitoring Mode**
   - Description: Monitor active TUI session continuously, poll logs every 5-10 seconds, alert on new issues immediately
   - Best for: Live debugging sessions where you want to catch issues as they happen
   - Note: Requires agent to be currently running

2. **Post-Mortem Analysis Mode**
   - Description: Analyze completed or failed runs in detail, deep dive into specific session
   - Best for: Understanding why a past execution failed
   - Note: Most common mode for debugging

3. **Historical Trends Mode**
   - Description: Analyze patterns across multiple runs, identify recurring issues
   - Best for: Finding systemic problems that happen repeatedly
   - Note: Useful for agents that have run many times

**Implementation:**
```
Use AskUserQuestion to present these options and let the developer choose.
Store the selected mode for the session.
```

---

### Stage 3: Triage (L1 Analysis)

**Objective:** Identify which sessions need attention

**What to do:**

1. **Query high-level run summaries** using the MCP tool:
   ```
   query_runtime_logs(
       agent_work_dir="{agent_work_dir}",
       status="needs_attention",
       limit=20
   )
   ```

2. **Analyze the results:**
   - Look for runs with `needs_attention: true`
   - Check `attention_summary.categories` for issue types
   - Note the `run_id` of problematic sessions
   - Check `status` field: "degraded", "failure", "in_progress"
   - **For forever-alive agents:** Sessions with status "in_progress" or "paused" are normal — these agents never reach "completed". Only flag sessions with `needs_attention: true` or actual error indicators (tool failures, retry loops, missing outputs). High step counts alone do not indicate a problem.

3. **Attention flag triggers to understand:**
   From runtime_logger.py, runs are flagged when:
   - retry_count > 3
   - escalate_count > 2
   - latency_ms > 60000
   - tokens_used > 100000
   - total_steps > 20

4. **Present findings to developer:**
   - Summarize how many runs need attention
   - List the most recent problematic runs
   - Show attention categories for each
   - Ask which run they want to investigate (if multiple)

**Example Output:**
```
Found 2 runs needing attention:

1. session_20260206_115718_e22339c5 (30 minutes ago)
   Status: degraded
   Categories: missing_outputs, retry_loops

2. session_20260206_103422_9f8d1b2a (2 hours ago)
   Status: failure
   Categories: tool_failures, high_latency

Which run would you like to investigate?
```

---

### Stage 4: Diagnosis (L2 Analysis)

**Objective:** Identify which nodes failed and what patterns exist

**What to do:**

1. **Query per-node details** using the MCP tool:
   ```
   query_runtime_log_details(
       agent_work_dir="{agent_work_dir}",
       run_id="{selected_run_id}",
       needs_attention_only=True
   )
   ```

2. **Categorize issues** using the Issue Taxonomy:

   **10 Issue Categories:**

   | Category | Detection Pattern | Meaning |
   |----------|------------------|---------|
   | **Missing Outputs** | `exit_status != "success"`, `attention_reasons` contains "missing_outputs" | Node didn't call set_output with required keys |
   | **Tool Errors** | `tool_error_count > 0`, `attention_reasons` contains "tool_failures" | Tool calls failed (API errors, timeouts, auth issues) |
   | **Retry Loops** | `retry_count > 3`, `verdict_counts.RETRY > 5` | Judge repeatedly rejecting outputs |
   | **Guard Failures** | `guard_reject_count > 0` | Output validation failed (wrong types, missing keys) |
   | **Stalled Execution** | `total_steps > 20`, `verdict_counts.CONTINUE > 10` | EventLoopNode not making progress. **Caveat:** Forever-alive agents may legitimately have high step counts — check if agent is blocked at a client-facing node (normal) vs genuinely stuck in a loop |
   | **High Latency** | `latency_ms > 60000`, `avg_step_latency > 5000` | Slow tool calls or LLM responses |
   | **Client-Facing Issues** | `client_input_requested` but no `user_input_received` | Premature set_output before user input |
   | **Edge Routing Errors** | `exit_status == "no_valid_edge"`, `attention_reasons` contains "routing_issue" | No edges match current state |
   | **Memory/Context Issues** | `tokens_used > 100000`, `context_overflow_count > 0` | Conversation history too long |
   | **Constraint Violations** | Compare output against goal constraints | Agent violated goal-level rules |

   **Forever-Alive Agent Caveat:** If the agent uses `terminal_nodes=[]`, sessions will never reach "completed" status. This is by design. When debugging these agents, focus on:
   - Whether individual node visits succeed (not whether the graph "finishes")
   - Quality of each loop iteration — are outputs improving or degrading across loops?
   - Whether client-facing nodes are correctly blocking for user input
   - Memory accumulation issues: stale data from previous loops, context overflow across many iterations
   - Conversation compaction behavior: is the conversation growing unbounded?

3. **Analyze each flagged node:**
   - Node ID and name
   - Exit status
   - Retry count
   - Verdict distribution (ACCEPT/RETRY/ESCALATE/CONTINUE)
   - Attention reasons
   - Total steps executed

4. **Present diagnosis to developer:**
   - List problematic nodes
   - Categorize each issue
   - Highlight the most severe problems
   - Show evidence (retry counts, error types)

**Example Output:**
```
Diagnosis for session_20260206_115718_e22339c5:

Problem Node: research
├─ Exit Status: escalate
├─ Retry Count: 5 (HIGH)
├─ Verdict Counts: {RETRY: 5, ESCALATE: 1}
├─ Attention Reasons: ["high_retry_count", "missing_outputs"]
├─ Total Steps: 8
└─ Categories: Missing Outputs + Retry Loops

Root Issue: The research node is stuck in a retry loop because it's not setting required outputs.
```

---

### Stage 5: Root Cause Analysis (L3 Analysis)

**Objective:** Understand exactly what went wrong by examining detailed logs

**What to do:**

1. **Query detailed tool/LLM logs** using the MCP tool:
   ```
   query_runtime_log_raw(
       agent_work_dir="{agent_work_dir}",
       run_id="{run_id}",
       node_id="{problem_node_id}"
   )
   ```

2. **Analyze based on issue category:**

   **For Missing Outputs:**
   - Check `step.tool_calls` for set_output usage
   - Look for conditional logic that skipped set_output
   - Check if LLM is calling other tools instead

   **For Tool Errors:**
   - Check `step.tool_results` for error messages
   - Identify error types: rate limits, auth failures, timeouts, network errors
   - Note which specific tool is failing

   **For Retry Loops:**
   - Check `step.verdict_feedback` from judge
   - Look for repeated failure reasons
   - Identify if it's the same issue every time

   **For Guard Failures:**
   - Check `step.guard_results` for validation errors
   - Identify missing keys or type mismatches
   - Compare actual output to expected schema

   **For Stalled Execution:**
   - Check `step.llm_response_text` for repetition
   - Look for LLM stuck in same action loop
   - Check if tool calls are succeeding but not progressing

3. **Extract evidence:**
   - Specific error messages
   - Tool call arguments and results
   - LLM response text
   - Judge feedback
   - Step-by-step progression

4. **Formulate root cause explanation:**
   - Clearly state what is happening
   - Explain why it's happening
   - Show evidence from logs

**Example Output:**
```
Root Cause Analysis for research:

Step-by-step breakdown:

Step 3:
- Tool Call: web_search(query="latest AI regulations 2026")
- Result: Found relevant articles and sources
- Verdict: RETRY
- Feedback: "Missing required output 'research_findings'. You found sources but didn't call set_output."

Step 4:
- Tool Call: web_search(query="AI regulation policy 2026")
- Result: Found additional policy information
- Verdict: RETRY
- Feedback: "Still missing 'research_findings'. Use set_output to save your findings."

Steps 5-7: Similar pattern continues...

ROOT CAUSE: The node is successfully finding research sources via web_search, but the LLM is not calling set_output to save the results. It keeps searching for more information instead of completing the task.
```

---

### Stage 6: Fix Recommendations

**Objective:** Provide actionable solutions the developer can implement

**What to do:**

Based on the issue category identified, provide specific fix recommendations using these templates:

#### Template 1: Missing Outputs (Client-Facing Nodes)

```markdown
## Issue: Premature set_output in Client-Facing Node

**Root Cause:** Node called set_output before receiving user input

**Fix:** Use STEP 1/STEP 2 prompt pattern

**File to edit:** `exports/{agent_name}/nodes/{node_name}.py`

**Changes:**
1. Update the system_prompt to include explicit step guidance:
   ```python
   system_prompt = """
   STEP 1: Analyze the user input and decide what action to take.
   DO NOT call set_output in this step.

   STEP 2: After receiving feedback or completing analysis,
   ONLY THEN call set_output with your results.
   """
   ```

2. If some inputs are optional (like feedback on retry edges), add nullable_output_keys:
   ```python
   nullable_output_keys=["feedback"]
   ```

**Verification:**
- Run the agent with test input
- Verify the client-facing node waits for user input before calling set_output
```

#### Template 2: Retry Loops

```markdown
## Issue: Judge Repeatedly Rejecting Outputs

**Root Cause:** {Insert specific reason from verdict_feedback}

**Fix Options:**

**Option A - If outputs are actually correct:** Adjust judge evaluation rules
- File: `exports/{agent_name}/agent.json`
- Update `evaluation_rules` section to accept the current output format
- Example: If judge expects list but gets string, update rule to accept both

**Option B - If prompt is ambiguous:** Clarify node instructions
- File: `exports/{agent_name}/nodes/{node_name}.py`
- Make system_prompt more explicit about output format and requirements
- Add examples of correct outputs

**Option C - If tool is unreliable:** Add retry logic with fallback
- Consider using alternative tools
- Add manual fallback option
- Update prompt to handle tool failures gracefully

**Verification:**
- Run the node with test input
- Confirm judge accepts output on first try
- Check that retry_count stays at 0
```

#### Template 3: Tool Errors

```markdown
## Issue: {tool_name} Failing with {error_type}

**Root Cause:** {Insert specific error message from logs}

**Fix Strategy:**

**If API rate limit:**
1. Add exponential backoff in tool retry logic
2. Reduce API call frequency
3. Consider caching results

**If auth failure:**
1. Check credentials using:
   ```bash
   /hive-credentials --agent {agent_name}
   ```
2. Verify API key environment variables
3. Update `mcp_servers.json` if needed

**If timeout:**
1. Increase timeout in `mcp_servers.json`:
   ```json
   {
     "timeout_ms": 60000
   }
   ```
2. Consider using faster alternative tools
3. Break large requests into smaller chunks

**Verification:**
- Test tool call manually
- Confirm successful response
- Monitor for recurring errors
```

#### Template 4: Edge Routing Errors

```markdown
## Issue: No Valid Edge from Node {node_id}

**Root Cause:** No edge condition matched the current state

**File to edit:** `exports/{agent_name}/agent.json`

**Analysis:**
- Current node output: {show actual output keys}
- Existing edge conditions: {list edge conditions}
- Why no match: {explain the mismatch}

**Fix:**
Add the missing edge to the graph:
```json
{
  "edge_id": "{node_id}_to_{target_node}",
  "source": "{node_id}",
  "target": "{target_node}",
  "condition": "on_success"
}
```

**Alternative:** Update existing edge condition to cover this case

**Verification:**
- Run agent with same input
- Verify edge is traversed successfully
- Check that execution continues to next node
```

#### Template 5: Stalled Execution

```markdown
## Issue: EventLoopNode Not Making Progress

**Root Cause:** {Insert analysis - e.g., "LLM repeating same failed action"}

**File to edit:** `exports/{agent_name}/nodes/{node_name}.py`

**Fix:** Update system_prompt to guide LLM out of loops

**Add this guidance:**
```python
system_prompt = """
{existing prompt}

IMPORTANT: If a tool call fails multiple times:
1. Try an alternative approach or different tool
2. If no alternatives work, call set_output with partial results
3. DO NOT retry the same failed action more than 3 times

Progress is more important than perfection. Move forward even with incomplete data.
"""
```

**Additional fix:** Lower max_iterations to prevent infinite loops
```python
# In node configuration
max_node_visits=3  # Prevent getting stuck
```

**Verification:**
- Run node with same input that caused stall
- Verify it exits after reasonable attempts (< 10 steps)
- Confirm it calls set_output eventually
```

#### Template 6: Checkpoint Recovery (Post-Fix Resume)

```markdown
## Recovery Strategy: Resume from Last Clean Checkpoint

**Situation:** You've fixed the issue, but the failed session is stuck mid-execution

**Solution:** Resume execution from a checkpoint before the failure

### Option A: Auto-Resume from Latest Checkpoint (Recommended)

Use CLI arguments to auto-resume when launching TUI:

```bash
PYTHONPATH=core:exports python -m {agent_name} --tui \
    --resume-session {session_id}
```

This will:
- Load session state from `state.json`
- Continue from where it paused/failed
- Apply your fixes immediately

### Option B: Resume from Specific Checkpoint (Time-Travel)

If you need to go back to an earlier point:

```bash
PYTHONPATH=core:exports python -m {agent_name} --tui \
    --resume-session {session_id} \
    --checkpoint {checkpoint_id}
```

Example:
```bash
PYTHONPATH=core:exports python -m deep_research_agent --tui \
    --resume-session session_20260208_143022_abc12345 \
    --checkpoint cp_node_complete_intake_143030
```

### Option C: Use TUI Commands

Alternatively, launch TUI normally and use commands:

```bash
# Launch TUI
PYTHONPATH=core:exports python -m {agent_name} --tui

# In TUI, use commands:
/resume {session_id}                    # Resume from session state
/recover {session_id} {checkpoint_id}   # Recover from specific checkpoint
```

### When to Use Each Option:

**Use `/resume` (or --resume-session) when:**
- You fixed credentials and want to retry
- Agent paused and you want to continue
- Agent failed and you want to retry from last state

**Use `/recover` (or --resume-session + --checkpoint) when:**
- You need to go back to an earlier checkpoint
- You want to try a different path from a specific point
- Debugging requires time-travel to earlier state

### Find Available Checkpoints:

Use MCP tools to programmatically find and inspect checkpoints:

```
# List all sessions to find the failed one
list_agent_sessions(agent_work_dir="~/.hive/agents/{agent_name}", status="failed")

# Inspect session state
get_agent_session_state(agent_work_dir="~/.hive/agents/{agent_name}", session_id="{session_id}")

# Find clean checkpoints to resume from
list_agent_checkpoints(agent_work_dir="~/.hive/agents/{agent_name}", session_id="{session_id}", is_clean="true")

# Compare checkpoints to understand what changed
compare_agent_checkpoints(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="{session_id}",
    checkpoint_id_before="cp_node_complete_intake_143030",
    checkpoint_id_after="cp_node_complete_research_143115"
)

# Inspect memory at a specific checkpoint
get_agent_checkpoint(agent_work_dir="~/.hive/agents/{agent_name}", session_id="{session_id}", checkpoint_id="cp_node_complete_intake_143030")
```

Or in TUI:
```bash
/sessions {session_id}
```

**Verification:**
- Use `--resume-session` to test your fix immediately
- No need to re-run from the beginning
- Session continues with your code changes applied
```

**Selecting the right template:**
- Match the issue category from Stage 4
- Customize with specific details from Stage 5
- Include actual error messages and code snippets
- Provide file paths and line numbers when possible
- **Always include recovery commands** (Template 6) after providing fix recommendations

---

### Stage 7: Verification Support

**Objective:** Help the developer confirm their fixes work

**What to do:**

1. **Suggest appropriate tests based on fix type:**

   **For node-level fixes:**
   ```bash
   # Use hive-test to run goal-based tests
   /hive-test --agent {agent_name} --goal {goal_id}

   # Or run specific test scenarios
   /hive-test --agent {agent_name} --scenario {specific_input}
   ```

   **For quick manual tests:**
   ```bash
   # Launch the interactive TUI dashboard
   hive tui
   ```
   Then use arrow keys to select the agent from the list and press Enter to run it.

2. **Provide MCP tool queries to validate the fix:**

   **Check if issue is resolved:**
   ```
   query_runtime_logs(
       agent_work_dir="~/.hive/agents/{agent_name}",
       status="needs_attention",
       limit=5
   )
   # Should show 0 results if fully fixed
   ```

   **Verify specific node behavior:**
   ```
   query_runtime_log_details(
       agent_work_dir="~/.hive/agents/{agent_name}",
       run_id="{new_run_id}",
       node_id="{fixed_node_id}"
   )
   # Should show exit_status="success", retry_count=0
   ```

3. **Monitor for regression:**
   - Run the agent multiple times
   - Check for similar issues reappearing
   - Verify fix works across different inputs

4. **Provide verification checklist:**
   ```
   Verification Checklist:
   □ Applied recommended fix to code
   □ Ran agent with test input
   □ Checked runtime logs show no attention flags
   □ Verified specific node completes successfully
   □ Tested with multiple inputs
   □ No regression of original issue
   □ Agent meets success criteria
   ```

**Example interaction:**
```
Developer: "I applied the fix to research. How do I verify it works?"

You: "Great! Let's verify the fix with these steps:

1. Launch the TUI dashboard:
   hive tui
   Then select your agent from the list and press Enter to run it.

2. After it completes, check the logs:
   [Use query_runtime_logs to check for attention flags]

3. Verify the specific node:
   [Use query_runtime_log_details for research]

Expected results:
- No 'needs_attention' flags
- research shows exit_status='success'
- retry_count should be 0

Let me know when you've run it and I'll help check the logs!"
```

---

## MCP Tool Usage Guide

### Three Levels of Observability

**L1: query_runtime_logs** - Session-level summaries
- **When to use:** Initial triage, identifying problematic runs, monitoring trends
- **Returns:** List of runs with status, attention flags, timestamps
- **Example:**
  ```
  query_runtime_logs(
      agent_work_dir="/home/user/.hive/deep_research_agent",
      status="needs_attention",
      limit=20
  )
  ```

**L2: query_runtime_log_details** - Node-level details
- **When to use:** Diagnosing which nodes failed, understanding retry patterns
- **Returns:** Per-node completion details, retry counts, verdicts
- **Example:**
  ```
  query_runtime_log_details(
      agent_work_dir="/home/user/.hive/deep_research_agent",
      run_id="session_20260206_115718_e22339c5",
      needs_attention_only=True
  )
  ```

**L3: query_runtime_log_raw** - Step-level details
- **When to use:** Root cause analysis, understanding exact failures
- **Returns:** Full tool calls, LLM responses, judge feedback
- **Example:**
  ```
  query_runtime_log_raw(
      agent_work_dir="/home/user/.hive/deep_research_agent",
      run_id="session_20260206_115718_e22339c5",
      node_id="research"
  )
  ```

### Session & Checkpoint Tools

**list_agent_sessions** - Browse sessions with filtering
- **When to use:** Finding resumable sessions, identifying failed sessions, Stage 3 triage
- **Returns:** Session list with status, timestamps, is_resumable, current_node, quality
- **Example:**
  ```
  list_agent_sessions(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      status="failed",
      limit=10
  )
  ```

**get_agent_session_state** - Load full session state (excludes memory values)
- **When to use:** Inspecting session progress, checking is_resumable, examining path
- **Returns:** Full state with memory_keys/memory_size instead of memory values
- **Example:**
  ```
  get_agent_session_state(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      session_id="session_20260208_143022_abc12345"
  )
  ```

**get_agent_session_memory** - Get memory contents from a session
- **When to use:** Stage 5 root cause analysis, inspecting produced data
- **Returns:** All memory keys+values, or a single key's value
- **Example:**
  ```
  get_agent_session_memory(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      session_id="session_20260208_143022_abc12345",
      key="twitter_handles"
  )
  ```

**list_agent_checkpoints** - List checkpoints for a session
- **When to use:** Stage 6 recovery, finding clean checkpoints to resume from
- **Returns:** Checkpoint summaries with type, node, clean status
- **Example:**
  ```
  list_agent_checkpoints(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      session_id="session_20260208_143022_abc12345",
      is_clean="true"
  )
  ```

**get_agent_checkpoint** - Load a specific checkpoint with full state
- **When to use:** Inspecting exact state at a checkpoint, comparing to current state
- **Returns:** Full checkpoint: memory snapshot, execution path, metrics
- **Example:**
  ```
  get_agent_checkpoint(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      session_id="session_20260208_143022_abc12345",
      checkpoint_id="cp_node_complete_intake_143030"
  )
  ```

**compare_agent_checkpoints** - Diff memory between two checkpoints
- **When to use:** Understanding data flow, finding where state diverged
- **Returns:** Memory diff (added/removed/changed keys) + execution path diff
- **Example:**
  ```
  compare_agent_checkpoints(
      agent_work_dir="/home/user/.hive/agents/twitter_outreach",
      session_id="session_20260208_143022_abc12345",
      checkpoint_id_before="cp_node_complete_intake_143030",
      checkpoint_id_after="cp_node_complete_research_143115"
  )
  ```

### Query Patterns

**Pattern 1: Top-Down Investigation** (Most common)
```
1. L1: Find problematic runs
2. L2: Identify failing nodes
3. L3: Analyze specific failures
```

**Pattern 2: Node-Specific Debugging**
```
1. L2: Get details for specific node across all runs
2. L3: Deep dive into worst failures
```

**Pattern 3: Real-time Monitoring**
```
Loop every 10 seconds:
  1. L1: Check for new needs_attention runs
  2. If found: Alert and drill into L2
```

**Pattern 4: Session State + Checkpoint Recovery**
```
1. list_agent_sessions: Find failed/paused sessions
2. get_agent_session_state: Check is_resumable, see execution path
3. get_agent_session_memory: Inspect what data was produced
4. list_agent_checkpoints: Find clean checkpoints before failure
5. compare_agent_checkpoints: Understand what changed between checkpoints
6. Recommend resume command with specific checkpoint
```

---

## Complete Example Walkthrough

### Scenario: deep_research_agent Agent Failing

**Developer says:** "My deep_research_agent keeps failing. It's not saving research findings correctly."

#### Stage 1: Setup
```
You: "I'll help debug the deep_research_agent agent. Let me gather context..."

[Read exports/deep_research_agent/agent.json]

Context:
- Agent: deep_research_agent
- Goal: deep-research
- Working Dir: ~/.hive/agents/deep_research_agent
- Success Criteria: ["Successfully send 5 personalized outreach messages"]
- Constraints: ["Must verify handle exists", "Must personalize message"]
- Nodes: research, profile-analyzer, message-composer, outreach-sender
```

#### Stage 2: Mode Selection
```
You: "Which debugging approach would you prefer?"

[Present 3 mode options using AskUserQuestion]

Developer selects: "Post-Mortem Analysis Mode"
```

#### Stage 3: Triage (L1)
```
You: "Querying runtime logs for problematic runs..."

[Call query_runtime_logs with status="needs_attention"]

Results:
- Found 1 run needing attention
- session_20260206_115718_e22339c5 (30 min ago)
- Status: degraded
- Categories: missing_outputs, retry_loops
```

#### Stage 4: Diagnosis (L2)
```
You: "Analyzing node-level details..."

[Call query_runtime_log_details for the session]

Results:
- Problem Node: research
- Exit Status: escalate
- Retry Count: 5
- Verdict Counts: {RETRY: 5, ESCALATE: 1}
- Attention Reasons: ["high_retry_count", "missing_outputs"]
- Total Steps: 8

Diagnosis: research has retry loop + missing outputs issue
Category: Missing Outputs + Retry Loops
```

#### Stage 5: Root Cause (L3)
```
You: "Drilling into detailed logs for research..."

[Call query_runtime_log_raw for node research]

Evidence:
Step 3: web_search("latest AI regulations 2026") → Found articles
  Verdict: RETRY
  Feedback: "Missing required output 'research_findings'. You found sources but didn't call set_output."

Step 4: web_search("AI regulation policy 2026") → Found more info
  Verdict: RETRY
  Feedback: "Still missing 'research_findings'. Use set_output to save your findings."

Steps 5-7: Same pattern repeats...

ROOT CAUSE: Node successfully finds handles but LLM doesn't call set_output. It keeps searching instead of completing.
```

#### Stage 6: Fix Recommendation
```
You: "Here's the fix for this issue:

## Issue: research Node Not Setting Outputs

**Root Cause:** Node successfully finds research sources but doesn't call set_output

**Category:** Missing Outputs

**File to edit:** exports/deep_research_agent/nodes/research.py

**Changes:**
Update the system_prompt to emphasize the output requirement:

```python
system_prompt = """
You are the Research node for the deep research agent.

Your task:
1. Search for relevant sources on the research topic
2. Extract key findings from each source
3. **CRITICAL: Call set_output(research_findings=[...]) immediately after gathering sufficient findings**

IMPORTANT: You MUST call set_output even if you found findings on the first search.
Do not continue searching indefinitely - set output and finish once you have enough data.

Output format:
{
  "research_findings": [{"source": "...", "summary": "...", "url": "..."}, ...]
}
"""
```

**Why this works:** The explicit instruction to call set_output immediately prevents the LLM from continuing to search after finding sufficient sources.
```

#### Stage 7: Verification
```
Developer: "I updated the prompt. How do I test it?"

You: "Let's verify the fix:

1. Launch the TUI dashboard:
   hive tui
   Then select your agent and press Enter to run it.

2. I'll check the logs after it runs..."

[Developer runs agent]

Developer: "It completed! Can you check if it worked?"

You: "Checking now..."

[Call query_runtime_log_details for the new run]

Results:
- Node: research
- Exit Status: success ✓
- Retry Count: 0 ✓
- Total Steps: 2 ✓
- No attention flags ✓

"Perfect! The fix worked. The research now:
- Completes successfully on first try
- No retries needed
- Calls set_output properly

Your agent should now work correctly!"
```

---

## Tips for Effective Debugging

1. **Always start with L1 logs** - Don't jump straight to detailed logs
2. **Focus on attention flags** - They highlight the real issues
3. **Compare verdict_feedback across steps** - Patterns reveal root causes
4. **Check tool error messages carefully** - They often contain the exact problem
5. **Consider the agent's goal** - Fixes should align with success criteria
6. **Test fixes immediately** - Quick verification prevents wasted effort
7. **Look for patterns across multiple runs** - One-time failures might be transient

## Common Pitfalls to Avoid

1. **Don't recommend code you haven't verified exists** - Always read files first
2. **Don't assume tool capabilities** - Check MCP server configs
3. **Don't ignore edge conditions** - Missing edges cause routing failures
4. **Don't overlook judge configuration** - Mismatched expectations cause retry loops
5. **Don't forget nullable_output_keys** - Optional inputs need explicit marking
6. **Don't diagnose "in_progress" as a failure for forever-alive agents** - Agents with `terminal_nodes=[]` are designed to never enter "completed" state. This is intentional. Focus on quality of individual node visits, not session completion status
7. **Don't ignore conversation memory issues in long-running sessions** - In continuous conversation mode, history grows across node transitions and loop iterations. Watch for context overflow (tokens_used > 100K), stale data from previous loops affecting edge conditions, and compaction failures that cause the LLM to lose important context
8. **Don't confuse "waiting for user" with "stalled"** - Client-facing nodes in forever-alive agents block for user input by design. A session paused at a client-facing node is working correctly, not stalled

---

## Storage Locations Reference

**New unified storage (default):**
- Logs: `~/.hive/agents/{agent_name}/sessions/session_YYYYMMDD_HHMMSS_{uuid}/logs/`
- State: `~/.hive/agents/{agent_name}/sessions/{session_id}/state.json`
- Conversations: `~/.hive/agents/{agent_name}/sessions/{session_id}/conversations/`

**Old storage (deprecated, still supported):**
- Logs: `~/.hive/agents/{agent_name}/runtime_logs/runs/{run_id}/`

The MCP tools automatically check both locations.

---

**Remember:** Your role is to be a debugging companion and thought partner. Guide the developer through the investigation, explain what you find, and provide actionable fixes. Don't just report errors - help understand and solve them.
