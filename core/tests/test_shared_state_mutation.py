"""
Regression test for Shared mutable state mutation across multiple instances and executions.

Tests cover:
- Node instances don't share mutable state (tools, functions, configs)
- Multiple executions of the same graph produce consistent results
- Defensive copying prevents cross-execution state leakage
"""
import pytest
from framework.runtime.core import Runtime
from framework.graph.worker_node import WorkerNode
from framework.graph.executor import GraphExecutor
from framework.graph.flexible_executor import FlexibleGraphExecutor
from framework.graph.judge import HybridJudge
from framework.llm.provider import Tool


@pytest.fixture
def runtime(tmp_path):
    """Create a temporary runtime for testing."""
    return Runtime(tmp_path)


def test_worker_node_does_not_share_tools_dict(runtime):
    """Test that multiple WorkerNode instances don't share the same tools dict."""
    shared_tools = {
        "tool1": Tool(name="tool1", description="Test", parameters={})
    } # Create a shared tools dict 
    
    # Create two worker nodes with the same tools reference
    worker1 = WorkerNode(
        runtime=runtime,
        tools=shared_tools
    )
    worker2 = WorkerNode(
        runtime=runtime,
        tools=shared_tools
    )
    
    worker1.tools["tool2"] = Tool(name="tool2", description="Test2", parameters={}) # modify one worker's tools
    
    assert "tool2" not in worker2.tools, "WorkerNode2 should not see tool2 added to WorkerNode1 (shared state bug!)"
    assert len(worker1.tools) == 2
    assert len(worker2.tools) == 1


def test_worker_node_does_not_share_functions_dict(runtime):
    """Test that multiple WorkerNode instances don't share the same functions dict."""
    shared_functions = {
        "func1": lambda x: x * 2
    }

    worker1 = WorkerNode(
        runtime=runtime,
        functions=shared_functions
    )
    worker2 = WorkerNode(
        runtime=runtime,
        functions=shared_functions
    )

    worker1.functions["func2"] = lambda x: x * 3

    assert "func2" not in worker2.functions, \
        "WorkerNode2 should not see func2 added to WorkerNode1 (shared state bug!)"


def test_graph_executor_does_not_share_tools_list(runtime):
    """Test that multiple GraphExecutor instances don't share the same tools list."""
    shared_tools = [
        Tool(name="tool1", description="Test", parameters={})
    ]
    
    # Create two executors
    executor1 = GraphExecutor(
        runtime=runtime,
        tools=shared_tools
    )
    executor2 = GraphExecutor(
        runtime=runtime,
        tools=shared_tools
    )
    
    executor1.tools.append(Tool(name="tool2", description="Test2", parameters={}))
    
    assert len(executor2.tools) == 1, "GraphExecutor2 should not see tool2 added to GraphExecutor1 (shared state bug!)"
    assert len(executor1.tools) == 2


def test_graph_executor_does_not_share_node_registry(runtime):
    """Test that multiple GraphExecutor instances don't share the same node_registry dict."""
    from framework.graph.node import LLMNode
    shared_registry = {"node1": LLMNode()}
    
    executor1 = GraphExecutor(
        runtime=runtime,
        node_registry=shared_registry
    )
    executor2 = GraphExecutor(
        runtime=runtime,
        node_registry=shared_registry
    )
    
    executor1.node_registry["node2"] = LLMNode()
    
    assert "node2" not in executor2.node_registry, "GraphExecutor2 should not see node2 added to GraphExecutor1 (shared state bug!)"


def test_flexible_executor_does_not_share_tools_dict(runtime):
    """Test that multiple FlexibleGraphExecutor instances don't share tools."""
    
    shared_tools = {
        "tool1": Tool(name="tool1", description="Test", parameters={})
    }
    
    executor1 = FlexibleGraphExecutor(
        runtime=runtime,
        tools=shared_tools
    )
    executor2 = FlexibleGraphExecutor(
        runtime=runtime,
        tools=shared_tools
    )
    
    executor1.tools["tool2"] = Tool(name="tool2", description="Test2", parameters={})
    
    assert "tool2" not in executor2.tools, "FlexibleGraphExecutor2 should not see tool2 added to FlexibleGraphExecutor1"
    assert "tool2" not in executor2.worker.tools, "Worker in FlexibleGraphExecutor2 should not see tool2"


def test_flexible_executor_does_not_share_functions_dict(runtime):
    """Test that multiple FlexibleGraphExecutor instances don't share functions."""
    shared_functions = {"func1": lambda x: x * 2}
    
    executor1 = FlexibleGraphExecutor(
        runtime=runtime,
        functions=shared_functions
    )
    executor2 = FlexibleGraphExecutor(
        runtime=runtime,
        functions=shared_functions
    )
    
    executor1.functions["func2"] = lambda x: x * 3
    
    assert "func2" not in executor2.functions
    assert "func2" not in executor2.worker.functions


def test_hybrid_judge_does_not_share_rules_list():
    """Test that multiple HybridJudge instances don't share the same rules list."""
    from framework.graph.plan import EvaluationRule, JudgmentAction
    
    shared_rules = [
        EvaluationRule(
            id="rule1",
            description="Test rule",
            condition="True",
            action=JudgmentAction.ACCEPT,
        )
    ]
    
    judge1 = HybridJudge(rules=shared_rules)
    judge2 = HybridJudge(rules=shared_rules)
    
    # Modify one judge's rules
    judge1.rules.append(
        EvaluationRule(
            id="rule2",
            description="Test rule 2",
            condition="False",
            action=JudgmentAction.RETRY,
        )
    )
    
    # Verify the other judge is NOT affected
    assert len(judge2.rules) == 1, "HybridJudge2 should not see rule2 added to HybridJudge1 (shared state bug!)"
    assert len(judge1.rules) == 2


def test_deterministic_execution_across_runs(runtime):
    """
    Test that executing the same graph multiple times produces consistent results.
    
    This is the key test that would fail before the fix due to accumulated state
    mutations across runs.
    """
    from framework.graph.edge import GraphSpec
    from framework.graph.node import NodeSpec
    from framework.graph.goal import Goal
    
    # ccreating a simple graph spec
    graph = GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        entry_node="test-node",
        terminal_nodes=["test-node"],
        nodes=[
            NodeSpec(
                id="test-node",
                name="Test Node",
                description="Test",
                node_type="function",
                function="test_func",
                input_keys=["value"],
                output_keys=["result"],
            )
        ],
        edges=[],
    )
    
    goal = Goal(
        id="test-goal",
        name="Test Goal",
        description="Test goal",
    )
    
    def test_func(value):
        return value * 2
    
    # Create executor with function
    from framework.graph.node import FunctionNode
    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"test-node": FunctionNode(test_func)},
    )
    
    # Run multiple times
    results = []
    for i in range(3):
        import asyncio
        result = asyncio.run(executor.execute(
            graph=graph,
            goal=goal,
            input_data={"value": 5},
        ))
        results.append(result)
    
    for i, result in enumerate(results):
        assert result.success, f"Run {i+1} should succeed: {result.error}"
        assert result.output.get("result") == 10, f"Run {i+1} should output 10"
    
    assert results[0].output == results[1].output == results[2].output, "Multiple runs should produce identical results (determinism check)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
