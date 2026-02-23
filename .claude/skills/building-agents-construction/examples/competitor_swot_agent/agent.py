"""
Competitor SWOT Agent (Recurring Mode)
Demonstrates a multi-step graph: Identify -> Research -> Synthesize -> Report
Includes state memory for "Delta" reporting on recurring cron schedules.
"""
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from framework.graph import NodeSpec, EdgeSpec, EdgeCondition, Goal, GraphSpec
from framework.runtime.agent_runtime import create_agent_runtime, EntryPointSpec
from framework.llm.provider import LLMResponse

# --- 1. MOCK LLM (Simulates Context-Aware Responses) ---
class MockLLMProvider:
    """A smart mock that returns the correct JSON based on the graph's expected output keys."""
    def __init__(self): 
        self.model = "mock-model"
    
    async def generate(self, messages, **kwargs):
        # We simulate the LLM returning all possible state updates.
        # The framework's GraphExecutor will pluck out the keys requested by the current Node.
        mock_response = {
            "competitors": ["Jira", "Asana", "Monday"],
            "raw_research": {
                "Jira": "Enterprise focused, complex UI.",
                "Asana": "General project management, timeline views."
            },
            "swot_analysis": "## SWOT Analysis\n**Strengths:** ...\n**Deltas Detected:** Competitor changed pricing this week.",
            "final_report": "SUCCESS: Report saved to competitor_analysis.md"
        }
        return json.dumps(mock_response)

    def complete(self, messages, **kwargs):
        return LLMResponse(content='{"thought": "Executing graph step..."}', model="mock")


# --- 2. NODES (The 4-Step Workflow) ---

# Node 1: Find Competitors
identify_node = NodeSpec(
    id="identify-competitors",
    name="Identify Competitors",
    description="Uses search to find top 3 competitors",
    node_type="llm_generate",
    # REMOVED: tools=["aden_tools.web_search"],
    input_keys=["target_company"],
    output_keys=["competitors"],
    system_prompt="Find top 3 competitors for {target_company}."
)

# Node 2: Deep Dive / Scrape
research_node = NodeSpec(
    id="research-competitors",
    name="Research Competitors",
    description="Scrapes pricing and feature pages",
    node_type="llm_generate",
    # REMOVED: tools=["aden_tools.web_scrape"],
    input_keys=["competitors"],
    output_keys=["raw_research"],
    system_prompt="Scrape feature and pricing pages for: {competitors}."
)

# Node 3: Reasoning & Deltas
synthesis_node = NodeSpec(
    id="synthesize-swot",
    name="Synthesize SWOT",
    description="Generates SWOT and compares against previous runs",
    node_type="llm_generate",
    input_keys=["raw_research", "previous_run_summary"], # Note the memory key!
    output_keys=["swot_analysis"],
    system_prompt="Analyze {raw_research}. If {previous_run_summary} exists, highlight what changed."
)

# Node 4: Action / Save
report_node = NodeSpec(
    id="report-results",
    name="Report Results",
    description="Saves artifact to disk",
    node_type="llm_generate",
    # REMOVED: tools=["aden_tools.write_to_file"],
    input_keys=["swot_analysis"],
    output_keys=["final_report"],
    system_prompt="Format {swot_analysis} as Markdown and save."
)

# --- 3. AGENT SETUP ---
class CompetitorSwotAgent:
    def __init__(self):
        self.goal = Goal(
            id="swot_recurring", 
            name="Recurring SWOT Intelligence", 
            description="Continuous competitor analysis", 
            success_criteria=[], 
            constraints=[]
        )

    # NEW: Added live_mode parameter
    async def run(self, input_data: dict, live_mode: bool = False):
        print(f"🚀 Initializing Graph for: {input_data.get('target_company')}")
        if input_data.get("previous_run_summary"):
            print("📅 [CRON MODE DETECTED] Loading memory from previous week...")
        
        # --- LLM Engine Toggle ---
        if live_mode:
            print("⚡ [LIVE MODE] Initializing Real LLM Engine...")
            # TODO: Import the actual framework provider here. 
            # Example: from framework.llm.provider import AnthropicProvider
            # llm_engine = AnthropicProvider(model="claude-3-5-sonnet-latest")
            
            # Temporary fallback until we know the exact import:
            raise NotImplementedError("Live mode requires the framework's real LLM provider import.")
        else:
            print("🧪 [MOCK MODE] Running offline without API keys...")
            llm_engine = MockLLMProvider()

        # Define the Sequential Graph
        graph = GraphSpec(
            id="swot-graph",
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
            llm=llm_engine, # Pass the toggled engine here
            tools=[], 
            tool_executor=lambda x: "mock_execution",
            storage_path=Path("./agent_storage"),
            entry_points=entry_points
        )

        await runtime.start()
        result = await runtime.trigger_and_wait("start", input_data)
        await runtime.stop()
        return result