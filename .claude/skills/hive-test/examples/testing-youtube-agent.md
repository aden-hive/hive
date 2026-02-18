# Example: Iterative Testing of a Research Agent

This example walks through the full iterative test loop for a research agent that searches the web, reviews findings, and produces a cited report.

## Agent Structure

```
exports/deep_research_agent/
├── agent.py          # Goal + graph: intake → research → review → report
├── nodes/__init__.py # Node definitions (system_prompt, input/output keys)
├── config.py         # Model config
├── mcp_servers.json  # Tools: web_search, web_scrape
└── tests/            # Test files (we'll create these)
```

**Goal:** "Rigorous Interactive Research" — find 5+ diverse sources, cite every claim, produce a complete report.

---

## Phase 1: Generate Tests

### Read the goal

```python
Read(file_path="exports/deep_research_agent/agent.py")
# Extract: goal_id="rigorous-interactive-research"
# success_criteria: source-diversity (>=5), citation-coverage (100%), report-completeness (90%)
# constraints: no-hallucination, source-attribution
```

### Get test guidelines

```python
result = generate_success_tests(
    goal_id="rigorous-interactive-research",
    goal_json='{"id": "rigorous-interactive-research", "success_criteria": [{"id": "source-diversity", "description": "Use multiple diverse sources", "target": ">=5"}, {"id": "citation-coverage", "description": "Every claim cites its source", "target": "100%"}, {"id": "report-completeness", "description": "Report answers the research questions", "target": "90%"}]}',
    node_names="intake,research,review,report",
    tool_names="web_search,web_scrape",
    agent_path="exports/deep_research_agent"
)
```

### Write tests

```python
Write(
    file_path="exports/deep_research_agent/tests/test_success_criteria.py",
    content=result["file_header"] + '''

@pytest.mark.asyncio
async def test_success_source_diversity(runner, auto_responder, mock_mode):
    """At least 5 diverse sources are found."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "impact of remote work on productivity"})
    finally:
        await auto_responder.stop()
    assert result.success, f"Agent failed: {result.error}"
    output = result.output or {}
    sources = output.get("sources", [])
    if isinstance(sources, list):
        assert len(sources) >= 5, f"Expected >= 5 sources, got {len(sources)}"

@pytest.mark.asyncio
async def test_success_citation_coverage(runner, auto_responder, mock_mode):
    """Every factual claim in the report cites its source."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "climate change effects on agriculture"})
    finally:
        await auto_responder.stop()
    assert result.success, f"Agent failed: {result.error}"
    output = result.output or {}
    report = output.get("report", "")
    # Check that report contains numbered references
    assert "[1]" in str(report) or "[source" in str(report).lower(), "Report lacks citations"

@pytest.mark.asyncio
async def test_success_report_completeness(runner, auto_responder, mock_mode):
    """Report addresses the original research question."""
    query = "pros and cons of nuclear energy"
    await auto_responder.start()
    try:
        result = await runner.run({"query": query})
    finally:
        await auto_responder.stop()
    assert result.success, f"Agent failed: {result.error}"
    output = result.output or {}
    report = output.get("report", "")
    assert len(str(report)) > 200, f"Report too short: {len(str(report))} chars"

@pytest.mark.asyncio
async def test_empty_query_handling(runner, auto_responder, mock_mode):
    """Agent handles empty input gracefully."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": ""})
    finally:
        await auto_responder.stop()
    output = result.output or {}
    assert not result.success or output.get("error"), "Should handle empty query"

@pytest.mark.asyncio
async def test_feedback_loop_terminates(runner, auto_responder, mock_mode):
    """Feedback loop between review and research terminates."""
    await auto_responder.start()
    try:
        result = await runner.run({"query": "quantum computing basics"})
    finally:
        await auto_responder.stop()
    visits = result.node_visit_counts or {}
    for node_id, count in visits.items():
        assert count <= 5, f"Node {node_id} visited {count} times"
'''
)
```

---

## Phase 2: First Execution

```python
run_tests(
    goal_id="rigorous-interactive-research",
    agent_path="exports/deep_research_agent",
    fail_fast=True
)
```

**Result:**
```json
{
  "overall_passed": false,
  "summary": {"total": 5, "passed": 3, "failed": 2, "pass_rate": "60.0%"},
  "failures": [
    {"test_name": "test_success_source_diversity", "details": "AssertionError: Expected >= 5 sources, got 2"},
    {"test_name": "test_success_citation_coverage", "details": "AssertionError: Report lacks citations"}
  ]
}
```

---

## Phase 3: Analyze (Iteration 1)

### Debug the first failure

```python
debug_test(
    goal_id="rigorous-interactive-research",
    test_name="test_success_source_diversity",
    agent_path="exports/deep_research_agent"
)
# Category: ASSERTION_FAILURE — Expected >= 5 sources, got 2
```

### Find the session and inspect memory

```python
list_agent_sessions(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    status="completed",
    limit=1
)
# → session_20260209_150000_abc12345

get_agent_session_memory(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    session_id="session_20260209_150000_abc12345",
    key="research_results"
)
# → Only 2 sources found. LLM stopped searching after 2 queries.
```

### Check LLM behavior in the research node

```python
query_runtime_log_raw(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    run_id="session_20260209_150000_abc12345",
    node_id="research"
)
# → LLM called web_search twice, got results, immediately called set_output.
# → Prompt doesn't instruct it to find at least 5 sources.
```

**Root cause:** The research node's system_prompt doesn't specify minimum source requirements.

---

## Phase 4: Fix (Iteration 1)

```python
Read(file_path="exports/deep_research_agent/nodes/__init__.py")

# Fix the research node prompt
Edit(
    file_path="exports/deep_research_agent/nodes/__init__.py",
    old_string='system_prompt="Search for information on the user\'s topic using web search."',
    new_string='system_prompt="Search for information on the user\'s topic using web search. You MUST find at least 5 diverse, authoritative sources. Use multiple different search queries with varied keywords. Do NOT call set_output until you have gathered at least 5 distinct sources from different domains."'
)
```

---

## Phase 5: Recover & Resume (Iteration 1)

The fix is to the `research` node. Since this was a `run_tests` execution (no checkpoints), we re-run from scratch:

```python
run_tests(
    goal_id="rigorous-interactive-research",
    agent_path="exports/deep_research_agent",
    fail_fast=True
)
```

**Result:**
```json
{
  "overall_passed": false,
  "summary": {"total": 5, "passed": 4, "failed": 1, "pass_rate": "80.0%"},
  "failures": [
    {"test_name": "test_success_citation_coverage", "details": "AssertionError: Report lacks citations"}
  ]
}
```

Source diversity now passes. Citation coverage still fails.

---

## Phase 3: Analyze (Iteration 2)

```python
debug_test(
    goal_id="rigorous-interactive-research",
    test_name="test_success_citation_coverage",
    agent_path="exports/deep_research_agent"
)
# Category: ASSERTION_FAILURE — Report lacks citations

# Check what the report node produced
list_agent_sessions(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    status="completed",
    limit=1
)
# → session_20260209_151500_def67890

get_agent_session_memory(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    session_id="session_20260209_151500_def67890",
    key="report"
)
# → Report text exists but uses no numbered references.
# → Sources are in memory but report node doesn't cite them.
```

**Root cause:** The report node's prompt doesn't instruct the LLM to include numbered citations.

---

## Phase 4: Fix (Iteration 2)

```python
Edit(
    file_path="exports/deep_research_agent/nodes/__init__.py",
    old_string='system_prompt="Write a comprehensive report based on the research findings."',
    new_string='system_prompt="Write a comprehensive report based on the research findings. You MUST include numbered citations [1], [2], etc. for every factual claim. At the end, include a References section listing all sources with their URLs. Every claim must be traceable to a specific source."'
)
```

---

## Phase 5: Resume (Iteration 2)

The fix is to the `report` node (the last node). To demonstrate checkpoint recovery, run via CLI:

```bash
# Run via CLI to get checkpoints
uv run hive run exports/deep_research_agent --input '{"topic": "climate change effects"}'

# After it runs, find the clean checkpoint before report
list_agent_checkpoints(
    agent_work_dir="~/.hive/agents/deep_research_agent",
    session_id="session_20260209_152000_ghi34567",
    is_clean="true"
)
# → cp_node_complete_review_152100 (after review, before report)

# Resume — skips intake, research, review entirely
uv run hive run exports/deep_research_agent \
  --resume-session session_20260209_152000_ghi34567 \
  --checkpoint cp_node_complete_review_152100
```

Only the `report` node re-runs with the fixed prompt, using research data from the checkpoint.

---

## Phase 6: Final Verification

```python
run_tests(
    goal_id="rigorous-interactive-research",
    agent_path="exports/deep_research_agent"
)
```

**Result:**
```json
{
  "overall_passed": true,
  "summary": {"total": 5, "passed": 5, "failed": 0, "pass_rate": "100.0%"}
}
```

All tests pass.

---

## Summary

| Iteration | Failure | Root Cause | Fix | Recovery |
|-----------|---------|------------|-----|----------|
| 1 | Source diversity (2 < 5) | Research prompt too vague | Added "at least 5 sources" to prompt | Re-run (no checkpoints) |
| 2 | No citations in report | Report prompt lacks citation instructions | Added citation requirements | Checkpoint resume (skipped 3 nodes) |

**Key takeaways:**
- Phase 3 analysis (session memory + L3 logs) identified root causes without guessing
- Checkpoint recovery in iteration 2 saved time by skipping 3 expensive nodes
- Final `run_tests` confirms all scenarios pass end-to-end
