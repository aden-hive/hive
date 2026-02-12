"""
Competitor SWOT Agent (Offline Mode)
Demonstrates a multi-step workflow: Identify -> Analyze -> Report
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from framework.graph import NodeSpec, EdgeSpec, EdgeCondition, Goal, GraphSpec
from framework.runtime.agent_runtime import create_agent_runtime, EntryPointSpec
from framework.llm.provider import LLMResponse

# --- 1. MOCK LLM (Simulates the "Thinking") ---
class MockLLMProvider:
    def __init__(self): self.model = "mock-model"
    
    async def generate(self, messages, **kwargs):
        # We need to simulate different responses based on which Node is running.
        # In a real agent, the prompt would guide this. Here, we just return generic success.
        return '{"action": "mock_step", "competitors": ["CompA", "CompB"], "swot_analysis": "Strengths: Good UI..."}'

    def complete(self, messages, **kwargs):
        return LLMResponse(content='{"thought": "Processing step..."}', model="mock")

# --- 2. NODES (The Workflow Steps) ---

# Step 1: Find Competitors
identify_node = NodeSpec(
    id="identify-competitors",
    name="Identify Competitors",
    description="Find top 3 competitors",
    node_type="llm_generate",
    input_keys=["target_company"],
    output_keys=["competitors"],
    system_prompt="Find competitors for {target_company}."
)

# Step 2: Analyze Them
analyze_node = NodeSpec(
    id="analyze-competitors",
    name="Analyze Competitors",
    description="Get SWOT data for each",
    node_type="llm_generate",
    input_keys=["competitors"],
    output_keys=["swot_data"],
    system_prompt="Analyze SWOT for {competitors}."
)

# Step 3: Write Report
report_node = NodeSpec(
    id="write-report",
    name="Write Report",
    description="Save final markdown",
    node_type="llm_generate",
    input_keys=["swot_data"],
    output_keys=["final_report"],
    system_prompt="Write report based on {swot_data}."
)

# --- 3. AGENT SETUP ---
class CompetitorSwotAgent:
    def __init__(self):
        self.goal = Goal(id="swot", name="SWOT Analysis", description="Analyze competitors", success_criteria=[], constraints=[])

    async def run(self, input_data: dict):
        print(f"🚀 Starting SWOT Analysis for: {input_data.get('target_company')}")
        
        # Define Graph
        graph = GraphSpec(
            id="swot-graph",
            goal_id=self.goal.id,
            entry_node="identify-competitors",
            terminal_nodes=["write-report"],
            nodes=[identify_node, analyze_node, report_node],
            edges=[
                EdgeSpec(id="1", source="identify-competitors", target="analyze-competitors", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="2", source="analyze-competitors", target="write-report", condition=EdgeCondition.ON_SUCCESS),
            ]
        )

        # Define Entry Point (The fix you found!)
        entry_points = [EntryPointSpec(id="start", entry_node="identify-competitors", trigger_type="manual", name="Start")]

        # Create Runtime
        runtime = create_agent_runtime(
            graph=graph,
            goal=self.goal,
            llm=MockLLMProvider(),
            tools=[], 
            tool_executor=lambda x: "mock",
            storage_path=Path("./agent_storage"),
            entry_points=entry_points
        )

        await runtime.start()
        result = await runtime.trigger_and_wait("start", input_data)
        await runtime.stop()
        return result