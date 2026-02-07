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

---

## Prerequisites

Before using this skill, ensure:
1. You have an exported agent in `exports/{agent_name}/`
2. The agent has been run at least once (logs exist)
3. Runtime logging is enabled (default in Hive framework)
4. You have access to the agent's working directory at `~/.hive/{agent_name}/`

---

## Workflow

### Stage 1: Setup & Context Gathering

**Objective:** Understand the agent being debugged

**What to do:**

1. **Ask the developer which agent needs debugging:**
   - Get agent name (e.g., "twitter_outreach", "deep_research_agent")
   - Confirm the agent exists in `exports/{agent_name}/`

2. **Determine agent working directory:**
   - Calculate: `~/.hive/{agent_name}/`
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
   - agent_work_dir (e.g., `/home/user/.hive/twitter_outreach`)
   - goal_id
   - success_criteria
   - constraints
   - node_ids

**Example:**
```
Developer: "My twitter_outreach agent keeps failing"

You: "I'll help debug the twitter_outreach agent. Let me gather context..."

[Read exports/twitter_outreach/agent.json]

Context gathered:
- Agent: twitter_outreach
- Goal: twitter-outreach-multi-loop
- Working Directory: /home/user/.hive/twitter_outreach
- Success Criteria: ["Successfully send 5 personalized outreach messages"]
- Constraints: ["Must verify handle exists", "Must personalize message"]
- Nodes: ["intake-collector", "profile-analyzer", "message-composer", "outreach-sender"]
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
   | **Stalled Execution** | `total_steps > 20`, `verdict_counts.CONTINUE > 10` | EventLoopNode not making progress |
   | **High Latency** | `latency_ms > 60000`, `avg_step_latency > 5000` | Slow tool calls or LLM responses |
   | **Client-Facing Issues** | `client_input_requested` but no `user_input_received` | Premature set_output before user input |
   | **Edge Routing Errors** | `exit_status == "no_valid_edge"`, `attention_reasons` contains "routing_issue" | No edges match current state |
   | **Memory/Context Issues** | `tokens_used > 100000`, `context_overflow_count > 0` | Conversation history too long |
   | **Constraint Violations** | Compare output against goal constraints | Agent violated goal-level rules |

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

Problem Node: intake-collector
├─ Exit Status: escalate
├─ Retry Count: 5 (HIGH)
├─ Verdict Counts: {RETRY: 5, ESCALATE: 1}
├─ Attention Reasons: ["high_retry_count", "missing_outputs"]
├─ Total Steps: 8
└─ Categories: Missing Outputs + Retry Loops

Root Issue: The intake-collector node is stuck in a retry loop because it's not setting required outputs.
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
Root Cause Analysis for intake-collector:

Step-by-step breakdown:

Step 3:
- Tool Call: web_search(query="@RomuloNevesOf")
- Result: Found Twitter profile information
- Verdict: RETRY
- Feedback: "Missing required output 'twitter_handles'. You found the handle but didn't call set_output."

Step 4:
- Tool Call: web_search(query="@RomuloNevesOf twitter")
- Result: Found additional Twitter information
- Verdict: RETRY
- Feedback: "Still missing 'twitter_handles'. Use set_output to save your findings."

Steps 5-7: Similar pattern continues...

ROOT CAUSE: The node is successfully finding Twitter handles via web_search, but the LLM is not calling set_output to save the results. It keeps searching for more information instead of completing the task.
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

**Selecting the right template:**
- Match the issue category from Stage 4
- Customize with specific details from Stage 5
- Include actual error messages and code snippets
- Provide file paths and line numbers when possible

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
       agent_work_dir="~/.hive/{agent_name}",
       status="needs_attention",
       limit=5
   )
   # Should show 0 results if fully fixed
   ```

   **Verify specific node behavior:**
   ```
   query_runtime_log_details(
       agent_work_dir="~/.hive/{agent_name}",
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
Developer: "I applied the fix to intake-collector. How do I verify it works?"

You: "Great! Let's verify the fix with these steps:

1. Launch the TUI dashboard:
   hive tui
   Then select your agent from the list and press Enter to run it.

2. After it completes, check the logs:
   [Use query_runtime_logs to check for attention flags]

3. Verify the specific node:
   [Use query_runtime_log_details for intake-collector]

Expected results:
- No 'needs_attention' flags
- intake-collector shows exit_status='success'
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
      agent_work_dir="/home/user/.hive/twitter_outreach",
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
      agent_work_dir="/home/user/.hive/twitter_outreach",
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
      agent_work_dir="/home/user/.hive/twitter_outreach",
      run_id="session_20260206_115718_e22339c5",
      node_id="intake-collector"
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

---

## Complete Example Walkthrough

### Scenario: twitter_outreach Agent Failing

**Developer says:** "My twitter_outreach agent keeps failing. It's not finding Twitter handles correctly."

#### Stage 1: Setup
```
You: "I'll help debug the twitter_outreach agent. Let me gather context..."

[Read exports/twitter_outreach/agent.json]

Context:
- Agent: twitter_outreach
- Goal: twitter-outreach-multi-loop
- Working Dir: ~/.hive/twitter_outreach
- Success Criteria: ["Successfully send 5 personalized outreach messages"]
- Constraints: ["Must verify handle exists", "Must personalize message"]
- Nodes: intake-collector, profile-analyzer, message-composer, outreach-sender
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
- Problem Node: intake-collector
- Exit Status: escalate
- Retry Count: 5
- Verdict Counts: {RETRY: 5, ESCALATE: 1}
- Attention Reasons: ["high_retry_count", "missing_outputs"]
- Total Steps: 8

Diagnosis: intake-collector has retry loop + missing outputs issue
Category: Missing Outputs + Retry Loops
```

#### Stage 5: Root Cause (L3)
```
You: "Drilling into detailed logs for intake-collector..."

[Call query_runtime_log_raw for node intake-collector]

Evidence:
Step 3: web_search("@RomuloNevesOf") → Found profile
  Verdict: RETRY
  Feedback: "Missing required output 'twitter_handles'. You found the handle but didn't call set_output."

Step 4: web_search("@RomuloNevesOf twitter") → Found more info
  Verdict: RETRY
  Feedback: "Still missing 'twitter_handles'. Use set_output to save your findings."

Steps 5-7: Same pattern repeats...

ROOT CAUSE: Node successfully finds handles but LLM doesn't call set_output. It keeps searching instead of completing.
```

#### Stage 6: Fix Recommendation
```
You: "Here's the fix for this issue:

## Issue: intake-collector Not Setting Outputs

**Root Cause:** Node successfully finds Twitter handles but doesn't call set_output

**Category:** Missing Outputs

**File to edit:** exports/twitter_outreach/nodes/intake_collector.py

**Changes:**
Update the system_prompt to emphasize the output requirement:

```python
system_prompt = """
You are the Intake Collector for the Twitter outreach agent.

Your task:
1. Extract Twitter handle from user input (URL or @mention)
2. Verify it's a valid Twitter handle format
3. **CRITICAL: Call set_output(twitter_handles=[handle]) immediately after finding valid handle**

IMPORTANT: You MUST call set_output even if you found the handle on the first try.
Do not continue searching once you have a valid handle - set output and finish.

Output format:
{
  "twitter_handles": ["@handle1", "@handle2", ...]
}
"""
```

**Why this works:** The explicit instruction to call set_output immediately prevents the LLM from continuing to search after finding the handle.
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
- Node: intake-collector
- Exit Status: success ✓
- Retry Count: 0 ✓
- Total Steps: 2 ✓
- No attention flags ✓

"Perfect! The fix worked. The intake-collector now:
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

---

## Storage Locations Reference

**New unified storage (default):**
- Logs: `~/.hive/{agent_name}/sessions/session_YYYYMMDD_HHMMSS_{uuid}/logs/`
- State: `~/.hive/{agent_name}/sessions/{session_id}/state.json`
- Conversations: `~/.hive/{agent_name}/sessions/{session_id}/conversations/`

**Old storage (deprecated, still supported):**
- Logs: `~/.hive/{agent_name}/runtime_logs/runs/{run_id}/`

The MCP tools automatically check both locations.

---

**Remember:** Your role is to be a debugging companion and thought partner. Guide the developer through the investigation, explain what you find, and provide actionable fixes. Don't just report errors - help understand and solve them.
