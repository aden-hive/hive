"""Node definitions for Coding Agent."""

from framework.graph import NodeSpec

# ---------------------------------------------------------------------------
# Node 1: Analyze Request
# ---------------------------------------------------------------------------
analyze_node = NodeSpec(
    id="analyze-request",
    name="Analyze Request",
    description="Understand the user's coding request and identify requirements.",
    node_type="llm_generate",
    input_keys=["request", "context_files"],
    output_keys=["requirements", "technologies"],
    system_prompt="""\
You are a Senior Software Architect. Analyze the user request.

Request: {request}
Context Files: {context_files}

Identify:
1. Core requirements (functional & non-functional).
2. Technologies/libraries to use or avoid.
3. Ambiguities that need clarification (assume reasonable defaults).

Output as raw JSON:
{{
  "requirements": ["..."],
  "technologies": ["..."],
  "ambiguities": ["..."]
}}
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Node 2: Create Plan
# ---------------------------------------------------------------------------
plan_node = NodeSpec(
    id="create-plan",
    name="Create Implementation Plan",
    description="Outline the steps and file structure for the solution.",
    node_type="llm_generate",
    input_keys=["requirements", "technologies"],
    output_keys=["plan", "file_structure"],
    system_prompt="""\
You are a Technical Lead. Create a step-by-step implementation plan.

Requirements: {requirements}
Tech Stack: {technologies}

1. Define the file structure.
2. break down implementation into steps.

Output as raw JSON:
{{
  "plan": "1. Set up project... 2. Implement core logic...",
  "file_structure": ["src/main.py", "tests/test_main.py"]
}}
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Node 3: Write Code
# ---------------------------------------------------------------------------
write_node = NodeSpec(
    id="write-code",
    name="Write Code",
    description="Implement the planned solution.",
    node_type="llm_generate",
    input_keys=["plan", "file_structure", "feedback"],
    # feedback might not exist on first pass, so handled via prompt availability
    output_keys=["code_files", "implementation_notes"],
    system_prompt="""\
You are a Staff Engineer. Write the code according to the plan.

Plan: {plan}
Files to create: {file_structure}
Previous Feedback (if any): {feedback}

Provide complete, working code for each file.

Output as raw JSON:
{{
  "code_files": {{
    "src/main.py": "import os...",
    "tests/test_main.py": "def test_example():..."
  }},
  "implementation_notes": "Added error handling for..."
}}
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 4: Review Code
# ---------------------------------------------------------------------------
review_node = NodeSpec(
    id="review-code",
    name="Review Code",
    description="Review the implementation for correctness and style.",
    node_type="llm_generate",
    input_keys=["code_files", "requirements"],
    output_keys=["approved", "feedback"],
    system_prompt="""\
You are a QA Engineer / Code Reviewer. valuable code against requirements.

Requirements: {requirements}
Code: {code_files}

Check for:
1. Logic errors.
2. Missing requirements.
3. Security issues.

If issues found, set "approved": false and provide specific feedback.

Output as raw JSON:
{{
  "approved": true,
  "feedback": "Code looks good. Meets all requirements."
}}
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Node 5: Finalize
# ---------------------------------------------------------------------------
finalize_node = NodeSpec(
    id="finalize-delivery",
    name="Finalize Delivery",
    description="Package the approved code for delivery.",
    node_type="llm_generate",
    input_keys=["code_files"],
    output_keys=["final_output"],
    system_prompt="""\
You are a Release Manager.
Summarize the delivered code.

Code Files: {code_files}

Output as raw JSON:
{{
  "final_output": "Succesfully generated [src/main.py, tests/test_main.py]"
}}
""",
    tools=[],
)

all_nodes = [
    analyze_node,
    plan_node,
    write_node,
    review_node,
    finalize_node,
]
