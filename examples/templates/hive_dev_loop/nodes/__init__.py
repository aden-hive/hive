"""Node definitions for Hive Dev Loop Agent."""

from framework.graph import NodeSpec

# --- Node 1: Lead Architect (Plan) ---
# Client-facing node that interacts with the user to create a plan.
plan_node = NodeSpec(
    id="plan",
    name="Lead Architect",
    description="Analyze user request and create a technical execution plan.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["task"],
    output_keys=["plan_brief"],
    system_prompt="""\
You are the Lead Architect for a TDD Software Engine.

**STEP 1 - Analysis:**
Analyze the user's request: {{task}}

**STEP 2 - Interaction:**
If the request is vague, ask clarifying questions.
If the request is clear, outline a 3-step technical plan:
1. File Structure
2. Key Classes/Functions
3. Testing Strategy

**STEP 3 - Handoff:**
Once the plan is solid, output the plan to the next node.
- set_output("plan_brief", "<detailed_technical_plan>")
""",
    tools=[],
)

# --- Node 2: Test Engineer (Write Test) ---
write_test_node = NodeSpec(
    id="write_test",
    name="Test Engineer",
    description="Write a comprehensive pytest suite based on the plan.",
    node_type="event_loop",
    input_keys=["plan_brief"],
    output_keys=["test_file_path"],
    system_prompt="""\
You are a Senior QA Engineer.

**Context:**
Plan: {{plan_brief}}

**Task:**
1. Create a Python test file (e.g., `test_solution.py`).
2. Write comprehensive `pytest` cases covering edge cases.
3. Ensure tests fail initially (Red phase of TDD).

**Action:**
- write_to_file(path="tests/test_solution.py", content="<code_here>")
- set_output("test_file_path", "tests/test_solution.py")
""",
    tools=["write_to_file"],
)

# --- Node 3: Senior Developer (Write Code) ---
write_code_node = NodeSpec(
    id="write_code",
    name="Senior Developer",
    description="Implement the solution to satisfy the tests.",
    node_type="event_loop",
    input_keys=["plan_brief", "test_file_path"],
    output_keys=["source_file_path"],
    system_prompt="""\
You are a Senior Python Developer.

**Context:**
Plan: {{plan_brief}}
Tests: {{test_file_path}}

**Task:**
1. Implement the solution code in `solution.py`.
2. Ensure code structure matches the test expectations.
3. Write clean, type-hinted, and documented code.

**Action:**
- write_to_file(path="solution.py", content="<code_here>")
- set_output("source_file_path", "solution.py")
""",
    tools=["write_to_file", "view_file"],
)

# --- Node 4: CI/CD Runner (Run Pytest) ---
run_pytest_node = NodeSpec(
    id="run_pytest",
    name="CI/CD Runner",
    description="Execute the test suite and capture results.",
    node_type="event_loop",
    input_keys=["test_file_path", "source_file_path"],
    output_keys=["test_status", "test_logs"],
    system_prompt="""\
You are a CI/CD Runner.

**Task:**
Execute the tests using `pytest`.

**Action:**
- execute_command_tool(command="pytest {{test_file_path}} -v")
- Analyze the output.
- If passed: set_output("test_status", "PASS")
- If failed: set_output("test_status", "FAIL")
- set_output("test_logs", "<full_console_output>")
""",
    tools=["execute_command_tool"],
)

# --- Node 5: Debugger (Conditional) ---
debug_node = NodeSpec(
    id="debugger",
    name="Debugger",
    description="Analyze failures and patch the code.",
    node_type="event_loop",
    input_keys=["test_logs", "source_file_path"],
    output_keys=[],
    system_prompt="""\
You are a Debugging Specialist.

**Context:**
Tests failed.
Logs: {{test_logs}}

**Task:**
1. Analyze the failure reason.
2. Read the source code using `view_file`.
3. Rewrite the source code using `write_to_file` to fix the bug.

**Action:**
- write_to_file(path="{{source_file_path}}", content="<fixed_code>")
""",
    tools=["view_file", "write_to_file"],
)

# --- Node 6: Project Manager (Report) ---
report_node = NodeSpec(
    id="report",
    name="Project Manager",
    description="Generate final completion report.",
    node_type="event_loop",
    input_keys=["source_file_path", "test_status"],
    output_keys=["final_report"],
    system_prompt="""\
You are the Project Manager.

**Task:**
The TDD cycle is complete.
1. Confirm all tests passed.
2. Provide a summary of the implemented solution.
3. List the files created.

**Action:**
- set_output("final_report", "Project completed successfully.")
""",
    tools=[],
)

# Export all nodes so agent.py can import them
__all__ = [
    "plan_node",
    "write_test_node",
    "write_code_node",
    "run_pytest_node",
    "debug_node",
    "report_node",
]
