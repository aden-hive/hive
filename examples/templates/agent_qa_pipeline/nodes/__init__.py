"""Node definitions for Agent QA Pipeline."""

from framework.graph.node import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect agent spec from user (file path, URL, or raw JSON)",
    node_type="event_loop",
    input_keys=[],
    output_keys=["agent_spec_path", "agent_spec_source"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are the intake specialist for an Agent QA Pipeline.

**STEP 1 — Greet and collect target (text only, NO tool calls):**
Ask the user for the agent they want to test. Accept:
- File path to agent.json (e.g., examples/templates/tech_news_reporter/agent.json)
- File path to agent.py (e.g., examples/templates/job_hunter/agent.py)
- Raw JSON content of an agent spec

Explain briefly that this pipeline performs:
- **Static Analysis**: Topology, patterns, edge consistency
- **Functional Testing**: Spec-level correctness validation
- **Resilience Testing**: Error handling and recovery patterns
- **Security Auditing**: OWASP LLM Top 10 checks

Keep it brief. One message, ask for the agent location.

After your message, call ask_user() to wait for the user's response.

**STEP 2 — After the user responds, call set_output:**
- set_output("agent_spec_path", "the file path or 'raw_json' if provided inline")
- set_output("agent_spec_source", "file" or "raw_json" depending on how spec was provided)

If the user provided raw JSON, store it in memory as well.""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=True,
)

load_agent_node = NodeSpec(
    id="load-agent",
    name="Load Agent",
    description="Parse and validate agent spec (deterministic, no LLM)",
    node_type="event_loop",
    input_keys=["agent_spec_path", "agent_spec_source"],
    output_keys=["agent_spec", "load_errors", "agent_metadata"],
    nullable_output_keys=["load_errors"],
    input_schema={},
    output_schema={},
    system_prompt="""You are an agent spec loader and validator.

Your task: Load and parse the target agent spec from the provided path or raw JSON.

**Instructions:**
1. If agent_spec_source is "file":
   - Read the file from agent_spec_path
   - If it's a .json file, parse the JSON
   - If it's a .py file, extract the graph structure (nodes, edges, goal)

2. If agent_spec_source is "raw_json":
   - Parse the raw JSON content from memory

3. Validate the spec structure:
   - Check for required fields: nodes, edges, entry_node
   - Validate each node has: id, name, description, node_type
   - Validate each edge has: id, source, target, condition
   - Check for unreachable nodes
   - Check for missing entry node

4. Extract metadata:
   - node_count: number of nodes
   - edge_count: number of edges
   - has_fan_out: boolean (any node with multiple ON_SUCCESS outgoing edges)
   - has_fan_in: boolean (any node with multiple incoming edges)
   - has_conditional_routing: boolean (any CONDITIONAL edges)
   - has_on_failure: boolean (any ON_FAILURE edges)
   - has_pause_nodes: boolean (graph has pause_nodes defined)
   - has_max_node_visits: boolean (any node has max_node_visits > 0)

**Output format:**
Use set_output for each:
- set_output("agent_spec", "<JSON string of the complete agent spec>")
- set_output("load_errors", "<JSON array of validation errors, or null if valid>")
- set_output("agent_metadata", "<JSON string with extracted metadata>")

If loading fails completely, set load_errors with the error and the pipeline will route to error reporting.""",
    tools=["read_file"],
    model=None,
    function=None,
    routes={},
    max_retries=2,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

static_analysis_node = NodeSpec(
    id="static-analysis",
    name="Static Analysis",
    description="Structural analysis: topology, patterns, edge consistency",
    node_type="event_loop",
    input_keys=["agent_spec", "agent_metadata"],
    output_keys=["static_analysis_results"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a static analyzer for Hive agent graphs.

Your task: Perform structural analysis of the target agent spec.

**Analysis Categories:**

1. **Topology Analysis:**
   - Graph shape (linear, tree, cyclic, mesh)
   - Connected components
   - Dead ends (nodes with no outgoing edges that aren't terminal)
   - Entry/exit points

2. **Pattern Detection:**
   - Fan-out patterns (parallel execution branches)
   - Fan-in patterns (convergence points)
   - Feedback loops (edges that create cycles)
   - Error recovery patterns (on_failure edges)

3. **Edge Consistency:**
   - All edge sources exist as nodes
   - All edge targets exist as nodes
   - No duplicate edge IDs
   - Valid condition types

4. **Node Quality:**
   - All nodes have meaningful descriptions
   - System prompts are present for event_loop nodes
   - Input/output keys are consistent across edges
   - Tools are specified where needed

5. **Framework Feature Usage:**
   - HITL pause_nodes usage
   - max_node_visits for loop control
   - nullable_output_keys for optional outputs
   - prompt_injection_shield presence

**Scoring:**
Assign a score (0-100) for each category and calculate an overall score.

**Output format:**
set_output("static_analysis_results", "<JSON string>")

Example output structure:
```json
{
  "topology": {
    "shape": "linear",
    "score": 85,
    "issues": ["No error recovery branches"],
    "recommendations": ["Add on_failure edge for graceful degradation"]
  },
  "patterns": {
    "detected": ["linear-pipeline"],
    "score": 70,
    "issues": ["No parallel execution", "No feedback loops"],
    "recommendations": ["Consider fan-out for independent tasks"]
  },
  "edge_consistency": {
    "score": 100,
    "issues": [],
    "recommendations": []
  },
  "node_quality": {
    "score": 90,
    "issues": ["Node 'research' has generic description"],
    "recommendations": ["Add specific description for 'research' node"]
  },
  "framework_features": {
    "score": 50,
    "issues": ["No pause_nodes", "No prompt_injection_shield"],
    "recommendations": ["Add HITL gates for user approval", "Enable prompt injection protection"]
  },
  "overall_score": 79,
  "summary": "The agent follows a linear pipeline pattern with good edge consistency but lacks error recovery and advanced framework features."
}
```""",
    tools=["read_file"],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

generate_test_plan_node = NodeSpec(
    id="generate-test-plan",
    name="Generate Test Plan",
    description="LLM generates test plan across 3 categories",
    node_type="event_loop",
    input_keys=["agent_spec", "agent_metadata", "static_analysis_results"],
    output_keys=["test_plan"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a test plan generator for Hive agents.

Your task: Create a comprehensive test plan across 3 categories based on the agent spec and static analysis.

**Test Categories:**

1. **Functional Tests** (5-7 tests):
   - Output key validation: Do nodes produce expected output keys?
   - Edge routing: Do conditions evaluate correctly?
   - Goal criteria coverage: Does the agent address all success criteria?
   - Input/output consistency: Are keys passed correctly between nodes?
   - Terminal node reachability: Can execution reach all terminal nodes?

2. **Resilience Tests** (3-5 tests):
   - Tool failure handling: How does the agent handle tool errors?
   - Missing input handling: What happens when required inputs are missing?
   - Retry behavior: Are retries configured appropriately?
   - on_failure edge coverage: Are failure handlers defined?
   - Max visits enforcement: Do feedback loops terminate?

3. **Security Tests** (3-5 tests):
   - Prompt injection via tool results: Is prompt_injection_shield enabled?
   - Data exposure: Are sensitive keys protected?
   - Tool access control: Are tools appropriately scoped?
   - Input validation: Are user inputs sanitized?
   - Output sanitization: Are outputs checked for sensitive data?

**For each test, specify:**
- test_id: Unique identifier
- category: functional, resilience, or security
- name: Short name
- description: What is being tested
- test_type: "static" (spec analysis) or "runtime" (would need execution)
- expected_outcome: What should happen
- potential_issues: What could go wrong

**Output format:**
set_output("test_plan", "<JSON string>")

Example structure:
```json
{
  "functional": [
    {
      "test_id": "F001",
      "name": "Output Key Validation",
      "description": "Verify all nodes produce their declared output keys",
      "test_type": "static",
      "expected_outcome": "All output keys are produced in success paths",
      "potential_issues": ["Missing set_output calls", "Key name mismatches"]
    }
  ],
  "resilience": [...],
  "security": [...],
  "total_tests": 15,
  "static_tests": 12,
  "runtime_tests": 3,
  "notes": "Runtime tests require sub-graph execution (Proposal 1)"
}
```""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

review_test_plan_node = NodeSpec(
    id="review-test-plan",
    name="Review Test Plan",
    description="User reviews and approves test plan (HITL pause)",
    node_type="event_loop",
    input_keys=["test_plan", "static_analysis_results", "agent_metadata"],
    output_keys=["plan_approved", "modified_tests", "test_preferences"],
    nullable_output_keys=["modified_tests", "test_preferences"],
    input_schema={},
    output_schema={},
    system_prompt="""You are a test plan reviewer for the Agent QA Pipeline.

**STEP 1 — Present test plan (text only, NO tool calls):**

Present the test plan in a clear, organized format:

```
📊 Test Plan for [Agent Name]
================================

📈 Static Analysis Summary:
- Overall Score: [X]/100
- Key Findings: [Top 3 issues]

🧪 Test Plan ([N] tests across 3 categories):

FUNCTIONAL TESTS ([N] tests):
- [test_id]: [name] - [description]
  Risk: [potential_issues]

RESILIENCE TESTS ([N] tests):
- [test_id]: [name] - [description]
  Risk: [potential_issues]

SECURITY TESTS ([N] tests):
- [test_id]: [name] - [description]
  Risk: [potential_issues]

📝 Notes:
- [Any runtime tests that need framework additions]
- [Any limitations or caveats]
```

**STEP 2 — Ask for approval:**
"Approve this test plan? You can also:
- Skip specific tests by ID
- Add custom tests
- Request more tests in a category"

After your message, call ask_user() to wait for the user's response.

**STEP 3 — After the user responds, call set_output:**
- set_output("plan_approved", "true" or "false")
- set_output("modified_tests", "<JSON with any modifications, or null>")
- set_output("test_preferences", "<JSON with test preferences, or null>")

If the user wants changes, update the test plan accordingly.""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=True,
)

run_functional_node = NodeSpec(
    id="run-functional",
    name="Run Functional Tests",
    description="Execute functional correctness tests",
    node_type="event_loop",
    input_keys=["agent_spec", "test_plan", "test_preferences"],
    output_keys=["functional_results"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a functional test executor for Hive agents.

Your task: Execute the functional tests from the test plan against the agent spec.

**For each functional test:**

1. Parse the test definition from test_plan.functional
2. Apply test_preferences (skip specified tests, add custom tests)
3. Perform the test (static analysis for now)
4. Record the result

**Test Execution:**

For static tests, analyze the agent spec:
- Output Key Validation: Check each node's output_keys are set in success scenarios
- Edge Routing: Verify condition_expr can be evaluated
- Goal Criteria Coverage: Map success_criteria to node outputs
- Input/Output Consistency: Trace data flow through edges
- Terminal Reachability: DFS from entry to terminals

**Output format:**
set_output("functional_results", "<JSON string>")

Example structure:
```json
{
  "category": "functional",
  "total_tests": 5,
  "passed": 4,
  "failed": 1,
  "skipped": 0,
  "score": 80,
  "results": [
    {
      "test_id": "F001",
      "name": "Output Key Validation",
      "status": "PASS",
      "details": "All nodes properly declare and should produce their output keys",
      "evidence": ["Node 'intake' -> research_brief", "Node 'research' -> articles_data"]
    },
    {
      "test_id": "F002",
      "name": "Edge Routing",
      "status": "FAIL",
      "details": "Conditional edge 'judge-to-fixes' has invalid expression syntax",
      "evidence": ["Edge 'judge-quality-to-request-fixes-conditional': missing closing bracket"]
    }
  ],
  "summary": "Functional tests show good output key coverage but edge routing needs attention."
}
```""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

run_resilience_node = NodeSpec(
    id="run-resilience",
    name="Run Resilience Tests",
    description="Execute resilience and fault tolerance tests",
    node_type="event_loop",
    input_keys=["agent_spec", "test_plan", "test_preferences"],
    output_keys=["resilience_results"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a resilience test executor for Hive agents.

Your task: Execute the resilience tests from the test plan against the agent spec.

**For each resilience test:**

1. Parse the test definition from test_plan.resilience
2. Apply test_preferences (skip specified tests, add custom tests)
3. Perform the test (static analysis for now)
4. Record the result

**Test Execution:**

For static tests, analyze the agent spec:
- Tool Failure Handling: Check for on_failure edges, retry_on configurations
- Missing Input Handling: Check for nullable_output_keys, default values
- Retry Behavior: Check max_retries values are reasonable
- on_failure Coverage: Count nodes with on_failure handlers vs total
- Max Visits Enforcement: Check feedback loops have max_node_visits

**Output format:**
set_output("resilience_results", "<JSON string>")

Example structure:
```json
{
  "category": "resilience",
  "total_tests": 4,
  "passed": 2,
  "failed": 2,
  "skipped": 0,
  "score": 50,
  "results": [
    {
      "test_id": "R001",
      "name": "Tool Failure Handling",
      "status": "FAIL",
      "details": "No on_failure edges defined for tool-using nodes",
      "evidence": ["Node 'research' uses web_search/web_scrape but has no failure handler"],
      "recommendation": "Add on_failure edge from research → error_handler"
    },
    {
      "test_id": "R002",
      "name": "Retry Configuration",
      "status": "PASS",
      "details": "All nodes have max_retries=3 which is appropriate",
      "evidence": ["intake: max_retries=3", "research: max_retries=3"]
    }
  ],
  "summary": "Resilience is weak - no error recovery patterns detected."
}
```""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

run_security_node = NodeSpec(
    id="run-security",
    name="Run Security Tests",
    description="Execute security tests (OWASP LLM Top 10)",
    node_type="event_loop",
    input_keys=["agent_spec", "test_plan", "test_preferences"],
    output_keys=["security_results"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a security test executor for Hive agents.

Your task: Execute the security tests from the test plan against the agent spec.

**For each security test:**

1. Parse the test definition from test_plan.security
2. Apply test_preferences (skip specified tests, add custom tests)
3. Perform the test (static analysis for now)
4. Record the result

**Test Execution (OWASP LLM Top 10 focus):**

For static tests, analyze the agent spec:
- Prompt Injection Shield: Check if prompt_injection_shield is configured
- Tool Result Sanitization: Check if tool outputs are scanned
- Data Exposure: Check for sensitive data in prompts/outputs
- Tool Access Control: Check tool scope is appropriate
- Input Validation: Check for input_schema definitions
- Output Sanitization: Check for output_schema definitions

**Output format:**
set_output("security_results", "<JSON string>")

Example structure:
```json
{
  "category": "security",
  "total_tests": 3,
  "passed": 1,
  "failed": 2,
  "skipped": 0,
  "score": 33,
  "results": [
    {
      "test_id": "S001",
      "name": "Prompt Injection Shield",
      "status": "FAIL",
      "details": "No prompt_injection_shield configured at graph level",
      "evidence": ["Graph spec does not include prompt_injection_shield setting"],
      "recommendation": "Add prompt_injection_shield: 'warn' to graph configuration",
      "severity": "HIGH"
    },
    {
      "test_id": "S002",
      "name": "Tool Result Sanitization",
      "status": "FAIL",
      "details": "web_scrape results flow directly to LLM without sanitization",
      "evidence": ["Node 'research' uses web_scrape, outputs to articles_data"],
      "recommendation": "Enable prompt injection scanning on tool results",
      "severity": "HIGH"
    },
    {
      "test_id": "S003",
      "name": "Input Validation",
      "status": "PASS",
      "details": "Input schemas are defined where needed",
      "evidence": ["Node 'intake' accepts user input with validation"]
    }
  ],
  "summary": "Security posture is weak - prompt injection protection needed.",
  "severity_counts": {"HIGH": 2, "MEDIUM": 0, "LOW": 0}
}
```""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

aggregate_results_node = NodeSpec(
    id="aggregate-results",
    name="Aggregate Results",
    description="Merge results from 3 parallel runners (deterministic)",
    node_type="event_loop",
    input_keys=[
        "functional_results",
        "resilience_results",
        "security_results",
        "static_analysis_results",
    ],
    output_keys=["aggregated_results"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are a results aggregator for the Agent QA Pipeline.

Your task: Combine results from all test categories into a unified report.

**Aggregation Steps:**

1. Parse results from:
   - functional_results: Functional test outcomes
   - resilience_results: Resilience test outcomes
   - security_results: Security test outcomes
   - static_analysis_results: Structural analysis findings

2. Calculate overall metrics:
   - total_tests: Sum of all tests
   - total_passed: Sum of passed tests
   - total_failed: Sum of failed tests
   - overall_score: Weighted average (static: 20%, functional: 30%, resilience: 25%, security: 25%)

3. Identify critical issues:
   - HIGH severity security issues
   - Failed resilience tests (no error recovery)
   - Structural problems from static analysis

4. Generate category summaries

**Output format:**
set_output("aggregated_results", "<JSON string>")

Example structure:
```json
{
  "summary": {
    "total_tests": 12,
    "passed": 7,
    "failed": 5,
    "skipped": 0,
    "overall_score": 58,
    "grade": "D"
  },
  "categories": {
    "static": {"score": 79, "grade": "C"},
    "functional": {"score": 80, "grade": "B"},
    "resilience": {"score": 50, "grade": "D"},
    "security": {"score": 33, "grade": "F"}
  },
  "critical_issues": [
    {"category": "security", "severity": "HIGH", "issue": "No prompt injection protection"},
    {"category": "resilience", "severity": "HIGH", "issue": "No error recovery patterns"}
  ],
  "by_category": {
    "functional": {...functional_results...},
    "resilience": {...resilience_results...},
    "security": {...security_results...}
  },
  "static_analysis": {...static_analysis_results...}
}
```

Grade scale:
- A: 90-100 (Excellent)
- B: 75-89 (Good)
- C: 60-74 (Fair)
- D: 40-59 (Poor)
- F: 0-39 (Critical)""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

judge_quality_node = NodeSpec(
    id="judge-quality",
    name="Judge Quality",
    description="Evaluate results, produce verdict",
    node_type="event_loop",
    input_keys=["aggregated_results"],
    output_keys=["verdict", "verdict_score", "verdict_reasoning"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are the quality judge for the Agent QA Pipeline.

Your task: Evaluate the aggregated results and produce a final verdict.

**Verdict Types:**

1. **PASS** (score >= 75):
   - Agent meets quality standards
   - Minor issues can be addressed later
   - Ready for deployment

2. **FAIL** (score < 50):
   - Agent has critical issues
   - Not suitable for deployment
   - Requires significant rework

3. **CONDITIONAL** (50 <= score < 75):
   - Agent has issues that should be fixed
   - Can proceed with caveats
   - Specific fixes recommended

**Decision Process:**

1. Review the aggregated_results
2. Consider severity of issues (HIGH severity auto-downgrades)
3. Check for critical blockers:
   - Any HIGH severity security issues → max CONDITIONAL
   - No error recovery → max CONDITIONAL
   - Unreachable nodes → FAIL

4. Generate verdict reasoning

**Output format:**
Use set_output for each:
- set_output("verdict", "PASS" or "CONDITIONAL" or "FAIL")
- set_output("verdict_score", "<numeric score 0-100>")
- set_output("verdict_reasoning", "<detailed explanation>")

Example reasoning:
"The agent scores 62/100 (CONDITIONAL). Functional tests pass at 80%, but resilience (50%) and security (33%) drag down the score. Critical issues: no prompt injection shield, no on_failure handlers. Fix these to achieve PASS status."

**Important:** The verdict determines the next step:
- PASS or FAIL → generate-report (final report)
- CONDITIONAL → request-fixes (feedback cycle)""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

generate_report_node = NodeSpec(
    id="generate-report",
    name="Generate Report",
    description="Generate HTML quality report",
    node_type="event_loop",
    input_keys=[
        "aggregated_results",
        "verdict",
        "verdict_score",
        "verdict_reasoning",
        "load_errors",
    ],
    output_keys=["report_file"],
    nullable_output_keys=["load_errors"],
    input_schema={},
    output_schema={},
    system_prompt="""You are a report generator for the Agent QA Pipeline.

Your task: Generate a comprehensive HTML quality report.

**Report Structure:**

1. **Header:**
   - Report title: "Agent QA Report"
   - Date generated
   - Target agent name/ID

2. **Verdict Banner:**
   - Large PASS/CONDITIONAL/FAIL badge (color-coded)
   - Score (0-100)
   - Grade letter (A-F)

3. **Executive Summary:**
   - Brief overview of findings
   - Key recommendations

4. **Category Breakdown:**
   - Static Analysis (with score and issues)
   - Functional Tests (with pass/fail details)
   - Resilience Tests (with pass/fail details)
   - Security Tests (with severity levels)

5. **Detailed Findings:**
   - For each failed test:
     - Test name and category
     - Issue description
     - Evidence
     - Recommendation

6. **Fix Suggestions (if CONDITIONAL):**
   - Prioritized list of fixes
   - Code snippets where applicable
   - Expected impact of each fix

7. **Appendix:**
   - Full test results (expandable)
   - Agent spec summary

**Design Requirements:**
- Professional, clean design
- Color-coded severity (red=critical, orange=warning, green=ok)
- Responsive layout
- Self-contained HTML (inline CSS)
- Print-friendly

**STEP 1 — Generate and save the report:**
Create the HTML content and save it:
- save_data(filename="agent_qa_report.html", data=<html_content>, data_dir=<data_dir>)

**STEP 2 — Set output:**
- set_output("report_file", "agent_qa_report.html")

If load_errors is present (agent failed to load), generate an error report instead.""",
    tools=["save_data"],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=False,
)

deliver_report_node = NodeSpec(
    id="deliver-report",
    name="Deliver Report",
    description="Present report with download link",
    node_type="event_loop",
    input_keys=["report_file", "verdict", "verdict_score", "verdict_reasoning"],
    output_keys=["delivery_status"],
    nullable_output_keys=[],
    input_schema={},
    output_schema={},
    system_prompt="""You are the report delivery node for the Agent QA Pipeline.

**STEP 1 — Serve the report:**
Use serve_file_to_user to deliver the HTML report:
- serve_file_to_user(filename="agent_qa_report.html", data_dir=<data_dir>, label="Agent QA Report", open_in_browser=True)

**STEP 2 — Present summary to user (text only, NO tool calls):**

Present a summary of the QA results:

```
📊 Agent QA Pipeline Complete
================================

🎯 Verdict: [PASS/CONDITIONAL/FAIL]
📈 Score: [X]/100 (Grade: [A-F])

📝 Summary:
[verdict_reasoning]

📁 Full Report:
The detailed HTML report has been opened in your browser.

[If CONDITIONAL:]
🔄 Feedback Cycle: This agent can be improved. Use the fix suggestions in the report and re-test.

[If PASS:]
✅ This agent meets quality standards and is ready for deployment.

[If FAIL:]
❌ This agent has critical issues. Review the report for details.
```

**STEP 3 — Set output:**
- set_output("delivery_status", "delivered")""",
    tools=["serve_file_to_user"],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=0,
    output_model=None,
    max_validation_retries=2,
    client_facing=True,
)

request_fixes_node = NodeSpec(
    id="request-fixes",
    name="Request Fixes",
    description="Present fix suggestions, collect updated spec",
    node_type="event_loop",
    input_keys=["aggregated_results", "verdict", "verdict_score", "verdict_reasoning"],
    output_keys=["continue_testing", "fix_suggestions", "updated_spec"],
    nullable_output_keys=["fix_suggestions", "updated_spec"],
    input_schema={},
    output_schema={},
    system_prompt="""You are the fix request node for the Agent QA Pipeline.

This node is reached when the verdict is CONDITIONAL. Your job is to present fix suggestions and ask if the user wants to re-test.

**STEP 1 — Present findings (text only, NO tool calls):**

```
⚠️ CONDITIONAL Verdict - Fixes Recommended
============================================

📊 Current Score: [X]/100 (Grade: [D/C])

🔧 Priority Fixes:

1. [HIGH] [Issue Title]
   - Problem: [description]
   - Fix: [specific fix]
   - Impact: [expected improvement]

2. [MEDIUM] [Issue Title]
   - Problem: [description]
   - Fix: [specific fix]
   - Impact: [expected improvement]

...

📝 Full details in the report.

Options:
- **Apply fixes and re-test**: Provide an updated agent spec
- **Skip re-test**: Accept current verdict and generate final report
```

After your message, call ask_user() to wait for the user's response.

**STEP 2 — After the user responds, call set_output:**

If user wants to re-test:
- set_output("continue_testing", "true")
- set_output("updated_spec", "<JSON string of updated agent spec, or path to updated file>")
- set_output("fix_suggestions", "<JSON of suggested fixes>")

If user wants to skip:
- set_output("continue_testing", "false")
- set_output("fix_suggestions", "<JSON of suggested fixes for reference>")
- set_output("updated_spec", null)

**Note:** This node has max_node_visits=3 to limit feedback cycles.""",
    tools=[],
    model=None,
    function=None,
    routes={},
    max_retries=3,
    retry_on=[],
    max_node_visits=3,
    output_model=None,
    max_validation_retries=2,
    client_facing=True,
)

__all__ = [
    "intake_node",
    "load_agent_node",
    "static_analysis_node",
    "generate_test_plan_node",
    "review_test_plan_node",
    "run_functional_node",
    "run_resilience_node",
    "run_security_node",
    "aggregate_results_node",
    "judge_quality_node",
    "generate_report_node",
    "deliver_report_node",
    "request_fixes_node",
]
