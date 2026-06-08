# Integration Test Reporting Skill

Run the Level 2 dummy agent integration test suite and produce a detailed HTML report with per-test input → outcome analysis.

## Trigger

User wants to run integration tests and see results:
- `/test-reporting`
- `/test-reporting test_component_queen_live.py`
- `/test-reporting --all`

## SOP: Running Tests

### Step 1: Select Scope

If the user provides a specific test file or pattern, use it. Otherwise run the full suite.

```bash
# Full suite
cd core && echo "1" | uv run python tests/dummy_agents/run_all.py --interactive 2>&1

# Specific file (requires manual provider setup)
cd core && uv run python -c "
import sys
sys.path.insert(0, '.')
from tests.dummy_agents.run_all import detect_available
from tests.dummy_agents.conftest import set_llm_selection

avail = detect_available()
claude = [p for p in avail if 'Claude Code' in p['name']]
if not claude:
    avail_names = [p['name'] for p in avail]
    raise RuntimeError(f'No Claude Code subscription. Available: {avail_names}')
provider = claude[0]
set_llm_selection(
    model=provider['model'],
    api_key=provider['api_key'],
    extra_headers=provider.get('extra_headers'),
    api_base=provider.get('api_base'),
)

import pytest
sys.exit(pytest.main([
    'tests/dummy_agents/TEST_FILE_HERE',
    '-v', '--override-ini=asyncio_mode=auto', '--no-header', '--tb=long',
    '--log-cli-level=WARNING', '--junitxml=/tmp/hive_test_results.xml',
]))
"
```

### Step 2: Collect Results

After the test run completes, collect:
1. **JUnit XML** from `--junitxml` output (if available)
2. **stdout/stderr** from the run
3. **Summary table** from `run_all.py` output (the Unicode table)

### Step 3: Generate HTML Report

Write the report to `/tmp/hive_integration_test_report.html`.

The report MUST include these sections:

#### Header
- Run timestamp (ISO 8601)
- Provider used (model name, source)
- Total tests / passed / failed / skipped
- Total wall-clock time
- Overall verdict: PASS (all green) or FAIL (with count)

#### Per-Test Table

For EVERY test (not just failures), include a row with:

| Column | Description |
|--------|-------------|
| Component | Test file grouping (e.g., `component_queen_live`) |
| Test Name | Function name (e.g., `test_queen_starts_in_planning_without_worker`) |
| Status | PASS / FAIL / SKIP / ERROR with color badge |
| Duration | Wall-clock seconds |
| What | One-line description of what the test verifies |
| How | How it works (setup → action → assertion) |
| Why | Why this test matters (what bug/behavior it catches) |
| Input | The input data or configuration (graph spec, initial prompt, phase, etc.) |
| Expected Outcome | What the test asserts |
| Actual Outcome | What actually happened (PASS: matches expected / FAIL: actual vs expected) |
| Failure Detail | For failures only: full traceback + diagnosis |

#### What / How / Why Descriptions

These MUST be derived from the test function's docstring and code. Read each test file to extract:
- **What**: From the docstring first line
- **How**: From the test body (what fixtures, what graph, what assertions)
- **Why**: From the docstring body or "Why this matters" section in the test module

Use these mappings for the component test files:

```
test_component_llm.py          → "LLM Provider" — streaming, tool calling, tokens
test_component_tools.py        → "Tool Registry + MCP" — connection, execution
test_component_event_loop.py   → "EventLoopNode" — iteration, output, stall
test_component_edges.py        → "Edge Evaluation" — conditional, priority
test_component_conversation.py → "Conversation Persistence" — storage, cursor
test_component_escalation.py   → "Escalation Flow" — worker→queen signaling
test_component_continuous.py   → "Continuous Mode" — conversation threading
test_component_queen.py        → "Queen Phase (Unit)" — phase state, tools, events
test_component_queen_live.py   → "Queen Phase (Live)" — real queen, real LLM
test_component_queen_state_machine.py → "Queen State Machine" — edge cases, races
test_component_worker_comms.py → "Worker Communication" — events, data flow
test_component_strict_outcomes.py → "Strict Outcomes" — exact path, output, quality
```

#### HTML Template

Use this structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Hive Integration Test Report — {timestamp}</title>
<style>
  :root { --pass: #22c55e; --fail: #ef4444; --skip: #f59e0b; --bg: #0f172a; --surface: #1e293b; --text: #e2e8f0; --muted: #94a3b8; --border: #334155; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'SF Mono', 'Fira Code', monospace; background: var(--bg); color: var(--text); padding: 2rem; line-height: 1.6; }
  h1, h2, h3 { font-weight: 600; }
  h1 { font-size: 1.5rem; margin-bottom: 1rem; }
  h2 { font-size: 1.2rem; margin: 2rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .card { background: var(--surface); padding: 1rem; border-radius: 8px; border: 1px solid var(--border); }
  .card .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }
  .card .value { font-size: 1.5rem; font-weight: 700; margin-top: 0.25rem; }
  .card .value.pass { color: var(--pass); }
  .card .value.fail { color: var(--fail); }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { background: var(--surface); position: sticky; top: 0; text-align: left; padding: 0.5rem; border-bottom: 2px solid var(--border); color: var(--muted); text-transform: uppercase; font-size: 0.7rem; }
  td { padding: 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover { background: rgba(255,255,255,0.03); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 700; }
  .badge.pass { background: rgba(34,197,94,0.2); color: var(--pass); }
  .badge.fail { background: rgba(239,68,68,0.2); color: var(--fail); }
  .badge.skip { background: rgba(245,158,11,0.2); color: var(--skip); }
  .detail { background: #1a1a2e; padding: 0.75rem; border-radius: 4px; margin-top: 0.5rem; font-size: 0.75rem; white-space: pre-wrap; overflow-x: auto; max-height: 200px; overflow-y: auto; }
  .component-header { background: var(--surface); padding: 0.75rem 0.5rem; font-weight: 600; font-size: 0.85rem; }
  .meta { color: var(--muted); font-size: 0.75rem; }
</style>
</head>
<body>
<h1>Hive Integration Test Report</h1>
<p class="meta">Generated: {timestamp} | Provider: {provider} | Duration: {duration}s</p>

<div class="summary">
  <div class="card"><div class="label">Total</div><div class="value">{total}</div></div>
  <div class="card"><div class="label">Passed</div><div class="value pass">{passed}</div></div>
  <div class="card"><div class="label">Failed</div><div class="value fail">{failed}</div></div>
  <div class="card"><div class="label">Verdict</div><div class="value {verdict_class}">{verdict}</div></div>
</div>

<h2>Test Results</h2>
<table>
<thead>
<tr>
  <th>Component</th>
  <th>Test</th>
  <th>Status</th>
  <th>Time</th>
  <th>What</th>
  <th>Input → Expected → Actual</th>
</tr>
</thead>
<tbody>
<!-- For each test: -->
<tr>
  <td>{component}</td>
  <td>{test_name}</td>
  <td><span class="badge {status_class}">{status}</span></td>
  <td>{duration}s</td>
  <td>{what_description}</td>
  <td>
    <strong>Input:</strong> {input_description}<br>
    <strong>Expected:</strong> {expected_outcome}<br>
    <strong>Actual:</strong> {actual_outcome}
    <!-- If failed: -->
    <div class="detail">{failure_traceback}</div>
  </td>
</tr>
</tbody>
</table>

<h2>Failure Analysis</h2>
<!-- Only if there are failures -->
<p>For each failure, provide:</p>
<ul>
  <li><strong>Root cause:</strong> Why it failed</li>
  <li><strong>Impact:</strong> What this means for the system</li>
  <li><strong>Suggested fix:</strong> How to address it</li>
</ul>

</body>
</html>
```

### Step 4: Output

1. Write the HTML file to `/tmp/hive_integration_test_report.html`
2. Print the file path so the user can open it
3. Print a concise summary to the terminal:
   ```
   Test Report: /tmp/hive_integration_test_report.html
   Result: 74/76 PASSED (2 failures)
   Failures:
     - parallel_merge::test_parallel_disjoint_output_keys
     - worker::test_worker_timestamped_note_artifact
   ```

## Key Rules

1. ALWAYS use `--junitxml` when running pytest to get structured results
2. ALWAYS read the test source files to populate What/How/Why columns — do not guess
3. For Input/Expected/Actual, extract from the test's graph spec, assertions, and result
4. Color-code everything: green for pass, red for fail, amber for skip
5. Include the full traceback for failures in a scrollable `<div class="detail">`
6. Group tests by component (file name) with a visual separator
7. The report must be self-contained HTML (no external CSS/JS dependencies)
