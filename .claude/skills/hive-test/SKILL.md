---
name: hive-test
description: Iterative agent testing with session recovery. Execute, analyze, fix, resume from checkpoints. Use when testing an agent, debugging test failures, or verifying fixes without re-running from scratch.
---

# Agent Testing

Test agents iteratively: execute, analyze failures, fix, resume from checkpoint, repeat.

## When to Use

- Testing a newly built agent against its goal
- Debugging a failing agent iteratively
- Verifying fixes without re-running expensive early nodes
- Running final regression tests before deployment

## Prerequisites

1. Agent package at `exports/{agent_name}/` (built with `/hive-create`)
2. Credentials configured (`/hive-credentials`)
3. `ANTHROPIC_API_KEY` set (or appropriate LLM provider key)

**Path distinction** (critical — don't confuse these):
- `exports/{agent_name}/` — agent source code (edit here)
- `~/.hive/agents/{agent_name}/` — runtime data: sessions, checkpoints, logs (read here)

---

## The Iterative Test Loop

This is the core workflow. Don't re-run the entire agent when a late node fails — analyze, fix, and resume from the last clean checkpoint.

```
┌──────────────────────────────────────┐
│ PHASE 1: Generate Test Scenarios     │
│ Goal → synthetic test inputs + tests │
└──────────────┬───────────────────────┘
               ↓
┌──────────────────────────────────────┐
│ PHASE 2: Execute                     │◄────────────────┐
│ Run agent (CLI or pytest)            │                 │
└──────────────┬───────────────────────┘                 │
               ↓                                         │
          Pass? ──yes──► PHASE 6: Final Verification     │
               │                                         │
               no                                        │
               ↓                                         │
┌──────────────────────────────────────┐                 │
│ PHASE 3: Analyze                     │                 │
│ Session + runtime logs + checkpoints │                 │
└──────────────┬───────────────────────┘                 │
               ↓                                         │
┌──────────────────────────────────────┐                 │
│ PHASE 4: Fix                         │                 │
│ Prompt / code / graph / goal         │                 │
└──────────────┬───────────────────────┘                 │
               ↓                                         │
┌──────────────────────────────────────┐                 │
│ PHASE 5: Recover & Resume            │─────────────────┘
│ Checkpoint resume OR fresh re-run    │
└──────────────────────────────────────┘
```

---

### Phase 1: Generate Test Scenarios

Create synthetic tests from the agent's goal, constraints, and success criteria.

#### Step 1a: Read the goal

```python
# Read goal from agent.py
Read(file_path="exports/{agent_name}/agent.py")
# Extract the Goal definition and convert to JSON string
```

#### Step 1b: Get test guidelines

```python
# Get constraint test guidelines
generate_constraint_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "...", "constraints": [...]}',
    agent_path="exports/{agent_name}"
)

# Get success criteria test guidelines
generate_success_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "...", "success_criteria": [...]}',
    node_names="intake,research,review,report",
    tool_names="web_search,web_scrape",
    agent_path="exports/{agent_name}"
)
```

These return `file_header`, `test_template`, `constraints_formatted`/`success_criteria_formatted`, and `test_guidelines`. They do NOT generate test code — you write the tests.

#### Step 1c: Write tests

```python
Write(
    file_path=result["output_file"],
    content=result["file_header"] + "\n\n" + your_test_code
)
```

#### Test writing rules

- Every test MUST be `async` with `@pytest.mark.asyncio`
- Every test MUST accept `runner, auto_responder, mock_mode` fixtures
- Use `await auto_responder.start()` before running, `await auto_responder.stop()` in `finally`
- Use `await runner.run(input_dict)` — this goes through AgentRunner → AgentRuntime → ExecutionStream
- Access output via `result.output.get("key")` — NEVER `result.output["key"]`
- `result.success=True` means no exception, NOT goal achieved — always check output
- Write 8-15 tests total, not 30+
- Each real test costs ~3 seconds + LLM tokens
- NEVER use `default_agent.run()` — it bypasses the runtime (no sessions, no logs, client-facing nodes hang)

#### Step 1d: Check existing tests

Before generating, check if tests already exist:

```python
list_tests(
    goal_id="your-goal-id",
    agent_path="exports/{agent_name}"
)
```

---

### Phase 2: Execute

Two execution paths, use the right one for your situation.

#### Iterative debugging (for complex agents)

Run the agent via CLI. This creates sessions with checkpoints at `~/.hive/agents/{agent_name}/sessions/`:

```bash
uv run hive run exports/{agent_name} --input '{"query": "test topic"}'
```

Sessions and checkpoints are saved automatically.

**Client-facing nodes**: Agents with `client_facing=True` nodes (interactive conversation) work in headless mode when run from a real terminal — the agent streams output to stdout and reads user input from stdin via a `>>> ` prompt. In non-interactive shells (like Claude Code's Bash tool), client-facing nodes will hang because there is no stdin. For testing interactive agents from Claude Code, use `run_tests` with mock mode or have the user run the agent manually in their terminal.

#### Automated regression (for CI or final verification)

Use the `run_tests` MCP tool to run all pytest tests:

```python
run_tests(
    goal_id="your-goal-id",
    agent_path="exports/{agent_name}"
)
```

Returns structured results:
```json
{
  "overall_passed": false,
  "summary": {"total": 12, "passed": 10, "failed": 2, "pass_rate": "83.3%"},
  "test_results": [{"test_name": "test_success_source_diversity", "status": "failed"}],
  "failures": [{"test_name": "test_success_source_diversity", "details": "..."}]
}
```

**Options:**
```python
# Run only constraint tests
run_tests(goal_id, agent_path, test_types='["constraint"]')

# Stop on first failure
run_tests(goal_id, agent_path, fail_fast=True)

# Parallel execution
run_tests(goal_id, agent_path, parallel=4)
```

**Note:** `run_tests` uses `AgentRunner` with `tmp_path` storage, so sessions are isolated per test run. For checkpoint-based recovery with persistent sessions, use CLI execution. Use `run_tests` for quick regression checks and final verification.

---

### Phase 3: Analyze Failures

When a test fails, drill down systematically. Don't guess — use the tools.

#### Step 3a: Get error category

```python
debug_test(
    goal_id="your-goal-id",
    test_name="test_success_source_diversity",
    agent_path="exports/{agent_name}"
)
```

Returns error category (`IMPLEMENTATION_ERROR`, `ASSERTION_FAILURE`, `TIMEOUT`, `IMPORT_ERROR`, `API_ERROR`) plus full traceback and suggestions.

#### Step 3b: Find the failed session

```python
list_agent_sessions(
    agent_work_dir="~/.hive/agents/{agent_name}",
    status="failed",
    limit=5
)
```

Returns session list with IDs, timestamps, current_node (where it failed), execution_quality.

#### Step 3c: Inspect session state

```python
get_agent_session_state(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="session_20260209_143022_abc12345"
)
```

Returns execution path, which node was current, step count, timestamps — but excludes memory values (to avoid context bloat). Shows `memory_keys` and `memory_size` instead.

#### Step 3d: Examine runtime logs (L2/L3)

```python
# L2: Per-node success/failure, retry counts
query_runtime_log_details(
    agent_work_dir="~/.hive/agents/{agent_name}",
    run_id="session_20260209_143022_abc12345",
    needs_attention_only=True
)

# L3: Exact LLM responses, tool call inputs/outputs
query_runtime_log_raw(
    agent_work_dir="~/.hive/agents/{agent_name}",
    run_id="session_20260209_143022_abc12345",
    node_id="research"
)
```

#### Step 3e: Inspect memory data

```python
# See what data a node actually produced
get_agent_session_memory(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="session_20260209_143022_abc12345",
    key="research_results"
)
```

#### Step 3f: Find recovery points

```python
list_agent_checkpoints(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="session_20260209_143022_abc12345",
    is_clean="true"
)
```

Returns checkpoint summaries with IDs, types (`node_start`, `node_complete`), which node, and `is_clean` flag. Clean checkpoints are safe resume points.

#### Step 3g: Compare checkpoints (optional)

To understand what changed between two points in execution:

```python
compare_agent_checkpoints(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="session_20260209_143022_abc12345",
    checkpoint_id_before="cp_node_complete_research_143030",
    checkpoint_id_after="cp_node_complete_review_143115"
)
```

Returns memory diff (added/removed/changed keys) and execution path diff.

---

### Phase 4: Fix Based on Root Cause

Use the analysis from Phase 3 to determine what to fix and where.

| Root Cause | What to Fix | Where to Edit |
|------------|------------|---------------|
| **Prompt issue** — LLM produces wrong output format, misses instructions | Node `system_prompt` | `exports/{agent}/nodes/__init__.py` |
| **Code bug** — TypeError, KeyError, logic error in Python | Agent code | `exports/{agent}/agent.py`, `nodes/__init__.py` |
| **Graph issue** — wrong routing, missing edge, bad condition_expr | Edges, node config | `exports/{agent}/agent.py` |
| **Tool issue** — MCP tool fails, wrong config, missing credential | Tool config | `exports/{agent}/mcp_servers.json`, `/hive-credentials` |
| **Goal issue** — success criteria too strict/vague, wrong constraints | Goal definition | `exports/{agent}/agent.py` (goal section) |
| **Test issue** — test expectations don't match actual agent behavior | Test code | `exports/{agent}/tests/test_*.py` |

#### Fix strategies by error category

**IMPLEMENTATION_ERROR** (TypeError, AttributeError, KeyError):
```python
# Read the failing code
Read(file_path="exports/{agent_name}/nodes/__init__.py")

# Fix the bug
Edit(
    file_path="exports/{agent_name}/nodes/__init__.py",
    old_string="results.get('videos')",
    new_string="(results or {}).get('videos', [])"
)
```

**ASSERTION_FAILURE** (test assertions fail but agent ran successfully):
- Check if the agent's output is actually wrong → fix the prompt
- Check if the test's expectations are unrealistic → fix the test
- Use `get_agent_session_memory` to see what the agent actually produced

**TIMEOUT / STALL** (agent runs too long):
- Check `node_visit_counts` for feedback loops hitting max_node_visits
- Check L3 logs for tool calls that hang
- Reduce `max_iterations` in loop_config or fix the prompt to converge faster

**API_ERROR** (connection, rate limit, auth):
- Verify credentials with `/hive-credentials`
- Check MCP server configuration

---

### Phase 5: Recover & Resume

After fixing the agent, decide whether to resume or re-run.

#### When to resume from checkpoint

Resume when ALL of these are true:
- The fix is to a node that comes AFTER existing clean checkpoints
- Clean checkpoints exist (from a CLI execution with checkpointing)
- The early nodes are expensive (web scraping, API calls, long LLM chains)

```bash
# Resume from the last clean checkpoint before the failing node
uv run hive run exports/{agent_name} \
  --resume-session session_20260209_143022_abc12345 \
  --checkpoint cp_node_complete_research_143030
```

This skips all nodes before the checkpoint and only re-runs the fixed node onward.

#### When to re-run from scratch

Re-run when ANY of these are true:
- The fix is to the entry node or an early node
- No checkpoints exist (e.g., agent was run via `run_tests`)
- The agent is fast (2-3 nodes, completes in seconds)
- You changed the graph structure (added/removed nodes/edges)

```bash
uv run hive run exports/{agent_name} --input '{"query": "test topic"}'
```

#### Inspecting a checkpoint before resuming

```python
get_agent_checkpoint(
    agent_work_dir="~/.hive/agents/{agent_name}",
    session_id="session_20260209_143022_abc12345",
    checkpoint_id="cp_node_complete_research_143030"
)
```

Returns the full checkpoint: shared_memory snapshot, execution_path, current_node, next_node, is_clean.

#### Loop back to Phase 2

After resuming or re-running, check if the fix worked. If not, go back to Phase 3.

---

### Phase 6: Final Verification

Once the iterative fix loop converges (the agent produces correct output), run the full automated test suite:

```python
run_tests(
    goal_id="your-goal-id",
    agent_path="exports/{agent_name}"
)
```

All tests should pass. If not, repeat the loop for remaining failures.

---

## Credential Requirements

**CRITICAL: Testing requires ALL credentials the agent depends on.** This includes both the LLM API key AND any tool-specific credentials (HubSpot, Brave Search, etc.).

### Prerequisites

Before running agent tests, you MUST collect ALL required credentials from the user.

**Step 1: LLM API Key (always required)**
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

**Step 2: Tool-specific credentials (depends on agent's tools)**

Inspect the agent's `mcp_servers.json` and tool configuration to determine which tools the agent uses, then check for all required credentials:

```python
from aden_tools.credentials import CredentialManager, CREDENTIAL_SPECS

creds = CredentialManager()

# Determine which tools the agent uses (from agent.json or mcp_servers.json)
agent_tools = [...]  # e.g., ["hubspot_search_contacts", "web_search", ...]

# Find all missing credentials for those tools
missing = creds.get_missing_for_tools(agent_tools)
```

Common tool credentials:
| Tool | Env Var | Help URL |
|------|---------|----------|
| HubSpot CRM | `HUBSPOT_ACCESS_TOKEN` | https://developers.hubspot.com/docs/api/private-apps |
| Brave Search | `BRAVE_SEARCH_API_KEY` | https://brave.com/search/api/ |
| Google Search | `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX` | https://developers.google.com/custom-search |

**Why ALL credentials are required:**
- Tests need to execute the agent's LLM nodes to validate behavior
- Tools with missing credentials will return error dicts instead of real data
- Mock mode bypasses everything, providing no confidence in real-world performance

### Mock Mode Limitations

Mock mode (`--mock` flag or `MOCK_MODE=1`) is **ONLY for structure validation**:

- Validates graph structure (nodes, edges, connections)
- Validates that `AgentRunner.load()` succeeds and the agent is importable
- Does NOT execute event_loop agents — MockLLMProvider never calls `set_output`, so event_loop nodes loop forever
- Does NOT test LLM reasoning, content quality, or constraint validation
- Does NOT test real API integrations or tool use

**Bottom line:** If you're testing whether an agent achieves its goal, you MUST use real credentials.

### Enforcing Credentials in Tests

When writing tests, **ALWAYS include credential checks**:

```python
import os
import pytest
from aden_tools.credentials import CredentialManager

pytestmark = pytest.mark.skipif(
    not CredentialManager().is_available("anthropic") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.fixture(scope="session", autouse=True)
def check_credentials():
    """Ensure ALL required credentials are set for real testing."""
    creds = CredentialManager()
    mock_mode = os.environ.get("MOCK_MODE")

    if not creds.is_available("anthropic"):
        if mock_mode:
            print("\nRunning in MOCK MODE - structure validation only")
        else:
            pytest.fail(
                "\nANTHROPIC_API_KEY not set!\n"
                "Set API key: export ANTHROPIC_API_KEY='your-key-here'\n"
                "Or run structure validation: MOCK_MODE=1 pytest exports/{agent}/tests/"
            )

    if not mock_mode:
        agent_tools = []  # Update per agent
        missing = creds.get_missing_for_tools(agent_tools)
        if missing:
            lines = ["\nMissing tool credentials!"]
            for name in missing:
                spec = creds.specs.get(name)
                if spec:
                    lines.append(f"  {spec.env_var} - {spec.description}")
            pytest.fail("\n".join(lines))
```

### User Communication

When the user asks to test an agent, **ALWAYS check for ALL credentials first**:

1. **Identify the agent's tools** from `mcp_servers.json`
2. **Check ALL required credentials** using `CredentialManager`
3. **Ask the user to provide any missing credentials** before proceeding
4. Collect ALL missing credentials in a single prompt — not one at a time

---

## Safe Test Patterns

### OutputCleaner

The framework automatically validates and cleans node outputs using a fast LLM at edge traversal time. Tests should still use safe patterns because OutputCleaner may not catch all issues.

### Safe Access (REQUIRED)

```python
# UNSAFE - will crash on missing keys
approval = result.output["approval_decision"]
category = result.output["analysis"]["category"]

# SAFE - use .get() with defaults
output = result.output or {}
approval = output.get("approval_decision", "UNKNOWN")

# SAFE - type check before operations
analysis = output.get("analysis", {})
if isinstance(analysis, dict):
    category = analysis.get("category", "unknown")

# SAFE - handle JSON parsing trap (LLM response as string)
import json
recommendation = output.get("recommendation", "{}")
if isinstance(recommendation, str):
    try:
        parsed = json.loads(recommendation)
        if isinstance(parsed, dict):
            approval = parsed.get("approval_decision", "UNKNOWN")
    except json.JSONDecodeError:
        approval = "UNKNOWN"
elif isinstance(recommendation, dict):
    approval = recommendation.get("approval_decision", "UNKNOWN")

# SAFE - type check before iteration
items = output.get("items", [])
if isinstance(items, list):
    for item in items:
        ...
```

### Helper Functions for conftest.py

```python
import json
import re

def _parse_json_from_output(result, key):
    """Parse JSON from agent output (framework may store full LLM response as string)."""
    response_text = result.output.get(key, "")
    json_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()
    try:
        return json.loads(json_text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return result.output.get(key)

def safe_get_nested(result, key_path, default=None):
    """Safely get nested value from result.output."""
    output = result.output or {}
    current = output
    for key in key_path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, str):
            try:
                json_text = re.sub(r'```json\s*|\s*```', '', current).strip()
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    current = parsed.get(key)
                else:
                    return default
            except json.JSONDecodeError:
                return default
        else:
            return default
    return current if current is not None else default

# Make available in tests
pytest.parse_json_from_output = _parse_json_from_output
pytest.safe_get_nested = safe_get_nested
```

### ExecutionResult Fields

**`result.success=True` means NO exception, NOT goal achieved**

```python
# WRONG
assert result.success

# RIGHT
assert result.success, f"Agent failed: {result.error}"
output = result.output or {}
approval = output.get("approval_decision")
assert approval == "APPROVED", f"Expected APPROVED, got {approval}"
```

All fields:
- `success: bool` — Completed without exception (NOT goal achieved!)
- `output: dict` — Complete memory snapshot (may contain raw strings)
- `error: str | None` — Error message if failed
- `steps_executed: int` — Number of nodes executed
- `total_tokens: int` — Cumulative token usage
- `total_latency_ms: int` — Total execution time
- `path: list[str]` — Node IDs traversed (may repeat in feedback loops)
- `paused_at: str | None` — Node ID if paused
- `session_state: dict` — State for resuming
- `node_visit_counts: dict[str, int]` — Visit counts per node (feedback loop testing)
- `execution_quality: str` — "clean", "degraded", or "failed"

### Test Count Guidance

**Write 8-15 tests, not 30+**

- 2-3 tests per success criterion
- 1 happy path test
- 1 boundary/edge case test
- 1 error handling test (optional)

Each real test costs ~3 seconds + LLM tokens. 12 tests = ~36 seconds, $0.12.

---

## Test Patterns

### Happy Path
```python
@pytest.mark.asyncio
async def test_happy_path(runner, auto_responder, mock_mode):
    """Test normal successful execution."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "python tutorials"})
    finally:
        await auto_responder.stop()
    assert result.success, f"Agent failed: {result.error}"
    output = result.output or {}
    assert output.get("report"), "No report produced"
```

### Boundary Condition
```python
@pytest.mark.asyncio
async def test_minimum_sources(runner, auto_responder, mock_mode):
    """Test at minimum source threshold."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "niche topic"})
    finally:
        await auto_responder.stop()
    assert result.success, f"Agent failed: {result.error}"
    output = result.output or {}
    sources = output.get("sources", [])
    if isinstance(sources, list):
        assert len(sources) >= 3, f"Expected >= 3 sources, got {len(sources)}"
```

### Error Handling
```python
@pytest.mark.asyncio
async def test_empty_input(runner, auto_responder, mock_mode):
    """Test graceful handling of empty input."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": ""})
    finally:
        await auto_responder.stop()
    # Agent should either fail gracefully or produce an error message
    output = result.output or {}
    assert not result.success or output.get("error"), "Should handle empty input"
```

### Feedback Loop
```python
@pytest.mark.asyncio
async def test_feedback_loop_terminates(runner, auto_responder, mock_mode):
    """Test that feedback loops don't run forever."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "test"})
    finally:
        await auto_responder.stop()
    visits = result.node_visit_counts or {}
    for node_id, count in visits.items():
        assert count <= 5, f"Node {node_id} visited {count} times — possible infinite loop"
```

---

## MCP Tool Reference

### Phase 1: Test Generation

```python
# Check existing tests
list_tests(goal_id, agent_path)

# Get constraint test guidelines (returns templates, NOT generated tests)
generate_constraint_tests(goal_id, goal_json, agent_path)
# Returns: output_file, file_header, test_template, constraints_formatted, test_guidelines

# Get success criteria test guidelines
generate_success_tests(goal_id, goal_json, node_names, tool_names, agent_path)
# Returns: output_file, file_header, test_template, success_criteria_formatted, test_guidelines
```

### Phase 2: Execution

```python
# Automated regression (no checkpoints, fresh runs)
run_tests(goal_id, agent_path, test_types='["all"]', parallel=-1, fail_fast=False)

# Run only specific test types
run_tests(goal_id, agent_path, test_types='["constraint"]')
run_tests(goal_id, agent_path, test_types='["success"]')
```

```bash
# Iterative debugging with checkpoints (via CLI)
uv run hive run exports/{agent_name} --input '{"query": "test"}'
```

### Phase 3: Analysis

```python
# Debug a specific failed test
debug_test(goal_id, test_name, agent_path)

# Find failed sessions
list_agent_sessions(agent_work_dir, status="failed", limit=5)

# Inspect session state (excludes memory values)
get_agent_session_state(agent_work_dir, session_id)

# Inspect memory data
get_agent_session_memory(agent_work_dir, session_id, key="research_results")

# Runtime logs: L1 summaries
query_runtime_logs(agent_work_dir, status="needs_attention")

# Runtime logs: L2 per-node details
query_runtime_log_details(agent_work_dir, run_id, needs_attention_only=True)

# Runtime logs: L3 tool/LLM raw data
query_runtime_log_raw(agent_work_dir, run_id, node_id="research")

# Find clean checkpoints
list_agent_checkpoints(agent_work_dir, session_id, is_clean="true")

# Compare checkpoints (memory diff)
compare_agent_checkpoints(agent_work_dir, session_id, cp_before, cp_after)
```

### Phase 5: Recovery

```python
# Inspect checkpoint before resuming
get_agent_checkpoint(agent_work_dir, session_id, checkpoint_id)
# Empty checkpoint_id = latest checkpoint
```

```bash
# Resume from checkpoint via CLI (headless)
uv run hive run exports/{agent_name} \
  --resume-session {session_id} --checkpoint {checkpoint_id}
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|-----------|
| Use `default_agent.run()` in tests | Use `runner.run()` with `auto_responder` fixtures (goes through AgentRuntime) |
| Re-run entire agent when a late node fails | Resume from last clean checkpoint |
| Treat `result.success` as goal achieved | Check `result.output` for actual criteria |
| Access `result.output["key"]` directly | Use `result.output.get("key")` |
| Fix random things hoping tests pass | Analyze L2/L3 logs to find root cause first |
| Write 30+ tests | Write 8-15 focused tests |
| Skip credential check | Use `/hive-credentials` before testing |
| Confuse `exports/` with `~/.hive/agents/` | Code in `exports/`, runtime data in `~/.hive/` |
| Use `run_tests` for iterative debugging | Use headless CLI with checkpoints for iterative debugging |
| Use headless CLI for final regression | Use `run_tests` for automated regression |
| Use `--tui` from Claude Code | Use headless `run` command — TUI hangs in non-interactive shells |
| Test client-facing nodes from Claude Code | Use mock mode, or have the user run the agent in their terminal |
| Run tests without reading goal first | Always understand the goal before writing tests |
| Skip Phase 3 analysis and guess | Use session + log tools to identify root cause |

---

## Example Walkthrough: Deep Research Agent

A complete iteration showing the test loop for an agent with nodes: `intake → research → review → report`.

### Phase 1: Generate tests

```python
# Read the goal
Read(file_path="exports/deep_research_agent/agent.py")

# Get success criteria test guidelines
result = generate_success_tests(
    goal_id="rigorous-interactive-research",
    goal_json='{"id": "rigorous-interactive-research", "success_criteria": [{"id": "source-diversity", "target": ">=5"}, {"id": "citation-coverage", "target": "100%"}, {"id": "report-completeness", "target": "90%"}]}',
    node_names="intake,research,review,report",
    tool_names="web_search,web_scrape",
    agent_path="exports/deep_research_agent"
)

# Write tests
Write(
    file_path=result["output_file"],
    content=result["file_header"] + "\n\n" + test_code
)
```

### Phase 2: First execution

```python
run_tests(
    goal_id="rigorous-interactive-research",
    agent_path="exports/deep_research_agent",
    fail_fast=True
)
```

Result: `test_success_source_diversity` fails — agent only found 2 sources instead of 5.

### Phase 3: Analyze

```python
# Debug the failing test
debug_test(
    goal_id="rigorous-interactive-research",
    test_name="test_success_source_diversity",
    agent_path="exports/deep_research_agent"
)
# → ASSERTION_FAILURE: Expected >= 5 sources, got 2

# Find the session
list_agent_sessions(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    status="completed",
    limit=1
)
# → session_20260209_150000_abc12345

# See what the research node produced
get_agent_session_memory(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    session_id="session_20260209_150000_abc12345",
    key="research_results"
)
# → Only 2 web_search calls made, each returned 1 source

# Check the LLM's behavior in the research node
query_runtime_log_raw(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    run_id="session_20260209_150000_abc12345",
    node_id="research"
)
# → LLM called web_search only twice, then called set_output
```

Root cause: The research node's prompt doesn't tell the LLM to search for at least 5 diverse sources. It stops after the first couple of searches.

### Phase 4: Fix the prompt

```python
Read(file_path="exports/deep_research_agent/nodes/__init__.py")

Edit(
    file_path="exports/deep_research_agent/nodes/__init__.py",
    old_string='system_prompt="Search for information on the user\'s topic."',
    new_string='system_prompt="Search for information on the user\'s topic. You MUST find at least 5 diverse, authoritative sources. Use multiple different search queries to ensure source diversity. Do not stop searching until you have at least 5 distinct sources."'
)
```

### Phase 5: Resume from checkpoint

For this example, the fix is to the `research` node. If we had run via CLI with checkpointing, we could resume from the checkpoint after `intake` to skip re-running intake:

```bash
# Check if clean checkpoint exists after intake
list_agent_checkpoints(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    session_id="session_20260209_150000_abc12345",
    is_clean="true"
)
# → cp_node_complete_intake_150005

# Resume from after intake, re-run research with fixed prompt
uv run hive run exports/deep_research_agent \
  --resume-session session_20260209_150000_abc12345 \
  --checkpoint cp_node_complete_intake_150005
```

Or for this simple case (intake is fast), just re-run:

```bash
uv run hive run exports/deep_research_agent --input '{"topic": "test"}'
```

### Phase 6: Final verification

```python
run_tests(
    goal_id="rigorous-interactive-research",
    agent_path="exports/deep_research_agent"
)
# → All 12 tests pass
```

---

## Test File Structure

```
exports/{agent_name}/
├── agent.py              ← Agent to test (goal, nodes, edges)
├── nodes/__init__.py     ← Node implementations (prompts, config)
├── config.py             ← Agent configuration
├── mcp_servers.json      ← Tool server config
└── tests/
    ├── conftest.py           ← Shared fixtures + safe access helpers
    ├── test_constraints.py   ← Constraint tests
    ├── test_success_criteria.py  ← Success criteria tests
    └── test_edge_cases.py    ← Edge case tests
```

## Integration with Other Skills

| Scenario | From | To | Action |
|----------|------|----|--------|
| Agent built, ready to test | `/hive-create` | `/hive-test` | Generate tests, start loop |
| Prompt fix needed | `/hive-test` Phase 4 | Direct edit | Edit `nodes/__init__.py`, resume |
| Goal definition wrong | `/hive-test` Phase 4 | `/hive-create` | Update goal, may need rebuild |
| Missing credentials | `/hive-test` Phase 3 | `/hive-credentials` | Set up credentials |
| Complex runtime failure | `/hive-test` Phase 3 | `/hive-debugger` | Deep L1/L2/L3 analysis |
| All tests pass | `/hive-test` Phase 6 | Done | Agent validated |
