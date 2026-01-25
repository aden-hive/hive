
import pytest
from core.framework.graph.plan import Plan, PlanStep, ActionSpec, ActionType
from core.framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition
from core.framework.graph.node import NodeSpec

class TestPlanValidation:
    def test_missing_dependency(self):
        step1 = PlanStep(
            id="step1", 
            description="Step 1", 
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["non_existent_step"]
        )
        plan = Plan(id="p1", goal_id="g1", description="desc", steps=[step1])
        errors = plan.validate()
        assert any("depends on missing step" in e for e in errors)

    def test_cycle_detection(self):
        step_a = PlanStep(
            id="step_a",
            description="Step A",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_b"]
        )
        step_b = PlanStep(
            id="step_b",
            description="Step B",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_a"]
        )
        plan = Plan(id="p2", goal_id="g1", description="desc", steps=[step_a, step_b])
        errors = plan.validate()
        assert any("dependency cycle" in e for e in errors)

    def test_valid_plan(self):
        step_a = PlanStep(
            id="step_a",
            description="Step A",
            action=ActionSpec(action_type=ActionType.FUNCTION)
        )
        step_b = PlanStep(
            id="step_b",
            description="Step B",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_a"]
        )
        plan = Plan(id="p3", goal_id="g1", description="desc", steps=[step_a, step_b])
        assert len(plan.validate()) == 0


class TestGraphValidation:
    def test_missing_input_mapping(self):
        node_a = NodeSpec(id="node_a", name="Node A", description="A", input_keys=[], output_keys=["out_a"])
        node_b = NodeSpec(id="node_b", name="Node B", description="B", input_keys=["in_b"], output_keys=[])
        
        edge = EdgeSpec(
            id="e1", source="node_a", target="node_b", 
            input_mapping={"in_b": "missing_output"} 
        )
        
        graph = GraphSpec(
            id="g1", goal_id="goal", entry_node="node_a",
            nodes=[node_a, node_b],
            edges=[edge],
            memory_keys=[]
        )
        
        errors = graph.validate()
        assert any("maps missing key" in e for e in errors)

    def test_missing_node_input(self):
        node_a = NodeSpec(id="node_a", name="Node A", description="A", input_keys=[], output_keys=[])
        node_b = NodeSpec(id="node_b", name="Node B", description="B", input_keys=["required_input"], output_keys=[])
        
        edge = EdgeSpec(id="e1", source="node_a", target="node_b")
        
        graph = GraphSpec(
            id="g2", goal_id="goal", entry_node="node_a",
            nodes=[node_a, node_b],
            edges=[edge],
            memory_keys=[]
        )
        
        errors = graph.validate()
        assert any("potentially missing required inputs" in e for e in errors)

    def test_graph_cycle(self):
        node_a = NodeSpec(id="node_a", name="Node A", description="A", input_keys=[], output_keys=[])
        node_b = NodeSpec(id="node_b", name="Node B", description="B", input_keys=[], output_keys=[])
        
        edge1 = EdgeSpec(id="e1", source="node_a", target="node_b", condition=EdgeCondition.ALWAYS)
        edge2 = EdgeSpec(id="e2", source="node_b", target="node_a", condition=EdgeCondition.ALWAYS)
        
        graph = GraphSpec(
            id="g3", goal_id="goal", entry_node="node_a",
            nodes=[node_a, node_b],
            edges=[edge1, edge2]
        )
        
        errors = graph.validate()
        assert any("Graph contains a cycle" in e for e in errors)

    def test_unreachable_node(self):
        node_a = NodeSpec(id="node_a", name="Node A", description="A", input_keys=[], output_keys=[])
        node_b = NodeSpec(id="node_b", name="Node B", description="B", input_keys=[], output_keys=[])
        
        # Edge only goes A -> A (self loop) or just A exists as entry. B is isolated.
        graph = GraphSpec(
            id="g4", goal_id="goal", entry_node="node_a",
            nodes=[node_a, node_b],
            edges=[]
        )
        
        errors = graph.validate()
        assert any("is unreachable from entry" in e for e in errors)
