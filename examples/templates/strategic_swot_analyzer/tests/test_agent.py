import pytest
from ..agent import (
    StrategicSwotAgent, 
    identify_node, 
    research_node, 
    synthesis_node, 
    report_node
)

def test_agent_initialization():
    """Verify the agent initializes with the correct strategic goal."""
    agent = StrategicSwotAgent()
    assert agent.goal.id == "strategic_swot_analysis"
    assert "Strategic" in agent.goal.name

def test_graph_node_wiring():
    """Verify that the nodes pass the correct state keys to each other."""
    # 1. Identify Node
    assert "target_company" in identify_node.input_keys
    assert "competitors" in identify_node.output_keys

    # 2. Research Node (Requires output from Identify)
    assert "competitors" in research_node.input_keys
    assert "raw_research" in research_node.output_keys

    # 3. Synthesis Node (Requires output from Research + Memory)
    assert "raw_research" in synthesis_node.input_keys
    assert "previous_run_summary" in synthesis_node.input_keys
    assert "swot_analysis" in synthesis_node.output_keys

    # 4. Report Node
    assert "swot_analysis" in report_node.input_keys
    assert "final_report" in report_node.output_keys