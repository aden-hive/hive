"""Node definitions for the QA Engineer Agent."""

from framework.graph.node import NodeSpec

# Node 1: Plan the testing strategy
planning_node = NodeSpec(
    id="planning",
    name="Test Planning",
    description="Analyze the user request, identify test suites, and plan the execution strategy.",
    node_type="event_loop",
    system_prompt="Analyze the user request. Identify what needs to be tested and formulate a clear test plan.",
    client_facing=True,
)

# Node 2: Exploratory UI Testing (GCU Subagent)
# Notice this is NOT connected via edges, it is a subagent.
ui_testing_node = NodeSpec(
    id="ui_testing",
    name="Exploratory UI Testing",
    description="Use browser tools to navigate the application and assert UI correctness.",
    node_type="gcu",
    system_prompt="Perform exploratory visual testing. Use browser tools to navigate to the target URLs and verify the UI state. Report findings back to the parent.",
    client_facing=False,
)

# Node 3: Execution Coordinator (Runs CLI tests and delegates UI tests)
execution_node = NodeSpec(
    id="test_execution",
    name="Test Execution",
    description="Execute CLI test scripts and delegate UI testing to the browser subagent.",
    node_type="event_loop",
    system_prompt=(
        "Execute the test plan. Use the execute_command_tool to run scripts (e.g., pytest, robot). "
        "If UI testing is required, use the delegate_to_sub_agent tool to call the 'ui_testing' agent."
    ),
    client_facing=False,
    sub_agents=["ui_testing"],  # CRITICAL FIX: Declaring the GCU node as a subagent
)

# Node 4: Compile results and create a report
reporting_node = NodeSpec(
    id="reporting",
    name="QA Report Generation",
    description="Compile logs, test results, and browser snapshots into a final QA report.",
    node_type="event_loop",
    system_prompt="Review all test outputs and visual findings. Create a comprehensive QA report summarizing bugs, passed tests, and recommendations.",
    client_facing=True,
)