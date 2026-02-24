from framework.graph import NodeSpec, EdgeSpec, EdgeCondition, Goal, GraphSpec
from framework.runtime.agent_runtime import create_agent_runtime
from pathlib import Path

# --- 1. DEFINE THE NODES ---

map_node = NodeSpec(
    id="map-dom",
    name="Map DOM Elements",
    description="Maps the UI using the external Playwright MCP tool",
    node_type="llm_generate",
    input_keys=["target_url"],
    output_keys=["dom_elements"],
    system_prompt="Use the browser MCP tool to analyze the UI structure for {target_url} and return the interactive DOM elements."
)

plan_node = NodeSpec(
    id="generate-test-plan",
    name="Generate Test Plan",
    description="Creates an executable test script based on the DOM map",
    node_type="llm_generate",
    input_keys=["dom_elements"],
    output_keys=["executable_plan"],
    system_prompt="Given these interactive elements: {dom_elements}. Generate a strict JSON array of actions (click, type, assert) to test the primary user flow."
)

execute_node = NodeSpec(
    id="execute-tests",
    name="Execute Test Suite",
    description="Runs the generated actions and logs assertions",
    node_type="llm_generate",
    input_keys=["executable_plan"],
    output_keys=["test_results"],
    system_prompt="Use the browser MCP tool to execute {executable_plan}. Output a pass/fail matrix."
)

# --- 2. AGENT SETUP ---

class AutoTestAIAgent:
    def __init__(self):
        self.goal = Goal(
            id="autotest_ui", 
            name="Autonomous UI Testing", 
            description="E2E UI testing relying on MCP browser tools", 
            success_criteria=[], 
            constraints=[]
        )

    async def run(self, input_data: dict):
        print(f"🚀 Initializing AutoTest AI Graph for: {input_data.get('target_url')}")
        
        graph = GraphSpec(
            id="qa-graph",
            goal_id=self.goal.id,
            entry_node="map-dom",
            terminal_nodes=["execute-tests"],
            nodes=[map_node, plan_node, execute_node],
            edges=[
                EdgeSpec(id="e1", source="map-dom", target="generate-test-plan", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="e2", source="generate-test-plan", target="execute-tests", condition=EdgeCondition.ON_SUCCESS),
            ]
        )

        # TODO: Align with the latest MCP runtime and EntryPointSpec post-#3861 mock deprecation
        runtime = create_agent_runtime(
            graph=graph,
            goal=self.goal,
            storage_path=Path("./qa_agent_storage")
        )

        await runtime.start()
        # Triggering the entry node directly pending the new routing updates
        result = await runtime.trigger_and_wait("map-dom", input_data)
        await runtime.stop()
        return result