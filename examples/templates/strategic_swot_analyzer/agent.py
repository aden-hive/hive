"""
Strategic SWOT Analysis Agent (Recurring Mode)
"""
import asyncio
from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, GraphSpec
from framework.runtime.agent_runtime import create_agent_runtime, EntryPointSpec
from framework.llm import LiteLLMProvider  

# Import the nodes from our new module
from .nodes import identify_node, research_node, synthesis_node, report_node
from .config import metadata

class StrategicSwotAgent:
    def __init__(self):
        self.goal = Goal(
            id="strategic_swot_analysis", 
            name=metadata.name, 
            description=metadata.description, 
            success_criteria=[], 
            constraints=[]
        )

    async def run(self, input_data: dict):
        print(f"🚀 Initializing Strategic Graph for: {input_data.get('target_company')}")
        
        if "previous_run_summary" not in input_data:
            input_data["previous_run_summary"] = "No previous run data. This is a fresh analysis."
            
        if input_data.get("previous_run_summary") and "fresh analysis" not in input_data.get("previous_run_summary"):
            print("📅 [CRON MODE DETECTED] Loading memory from previous week...")
        
        llm_engine = LiteLLMProvider() 

        graph = GraphSpec(
            id="strategic-swot-graph",
            goal_id=self.goal.id,
            entry_node="identify-competitors",
            terminal_nodes=["report-results"],
            nodes=[identify_node, research_node, synthesis_node, report_node],
            edges=[
                EdgeSpec(id="e1", source="identify-competitors", target="research-competitors", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="e2", source="research-competitors", target="synthesize-swot", condition=EdgeCondition.ON_SUCCESS),
                EdgeSpec(id="e3", source="synthesize-swot", target="report-results", condition=EdgeCondition.ON_SUCCESS),
            ]
        )

        entry_points = [EntryPointSpec(id="start", entry_node="identify-competitors", trigger_type="manual", name="Start")]

        runtime = create_agent_runtime(
            graph=graph,
            goal=self.goal,
            llm=llm_engine,
            tools=[], 
            storage_path=Path("./agent_storage"),
            entry_points=entry_points
        )

        await runtime.start()
        result = await runtime.trigger_and_wait("start", input_data)
        await runtime.stop()
        return result