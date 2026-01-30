"""Tests for the BuilderWorkflow interface - how Builder analyzes agent runs."""

from framework.builder.workflow import GraphBuilder , BuildPhase
from framework.graph.goal import Goal, SuccessCriterion
from framework.graph.node import NodeSpec
from framework.graph.edge import EdgeSpec , EdgeCondition
from pathlib import Path
from framework.builder.workflow import TestCase , TestResult , ValidationResult
from unittest.mock import MagicMock
from types import SimpleNamespace



def return_goal(id: str , name: str , desc: str , sc: SuccessCriterion , cons: list, cap: list) -> Goal:
    return Goal(
        id=id,
        name=name,
        constraints=cons,
        description=desc,
        success_criteria=[sc],
        required_capabilities=cap
    )

def return_node(id: str , name: str , desc: str, input_keys: list[str] , output_keys: list[str] , tools: list[str], type: str) -> NodeSpec:
    return NodeSpec(
        id=id,
        name=name,
        node_type=type,
        description=desc,
        input_keys=input_keys,
        output_keys=output_keys,
        tools=tools
    )

def setup_builder_for_run_test(tmp_path):
    builder = GraphBuilder("graph_1", storage_path=tmp_path)
    builder.session.goal = MagicMock()
    builder._save_session = MagicMock()
    builder._build_graph = MagicMock(return_value="graph")
    return builder


class TestGraphBuilder:
    def test_validate_goal(self , tmp_path: Path):
        """"Test Goal Validation"""
        goal = Goal(
            id="goal_1",
            name="Test Goal",
            description="A test goal",
            success_criteria=[
                SuccessCriterion(id="sc1", description="Must succeed" , metric="status" , target="success")
            ],
            constraints=[],
            required_capabilities=["llm"],
        )

        builder = GraphBuilder("graph_1", storage_path=tmp_path)
        validation = builder.set_goal(goal)

        assert validation.valid

    def test_validate_goal_errors(self , tmp_path:Path):
        """"Test Error during Goal Validation"""
        goal = Goal(
            id="",
            name="",
            description="",
            success_criteria=[
                SuccessCriterion(id="sc1", description="Must succeed" , metric="status" , target="success")
            ],
            constraints=[],
            required_capabilities=["llm"],
        )

        builder = GraphBuilder("", storage_path=tmp_path)
        validation = builder.set_goal(goal)

        assert "Goal must have an id" in validation.errors
        assert "Goal must have a name" in validation.errors
        assert "Goal must have a description" in validation.errors
        

    def test_add_node_warnings(self, tmp_path: Path):
        """Test Node addition"""
        goal = Goal(
            id="goal_1",
            name="Test Goal",
            description="A test goal",
            success_criteria=[
                SuccessCriterion(
                    id="sc1",
                    description="Must succeed",
                    metric="status",
                    target="success",
                )
            ],
            constraints=[],
            required_capabilities=["llm"],
        )

        node = NodeSpec(
            id="node_id",
            name="node_name",
            description="node used for something",
            input_keys=["key1", "key2"],
            output_keys=["key1", "key2"],
            tools=["tool_1" , "tool_2"]
        )

        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        validation = builder.set_goal(goal)
        assert validation.valid

        approved = builder.approve("goal ok")
        assert approved is True

        node_validation = builder.add_node(node)

        assert node_validation.valid is True
        assert node_validation.errors == []
        assert node_validation.warnings == [
            "LLM node 'node_id' should have a system_prompt"
        ]
        assert node_validation.suggestions == []
    
        node_validation_1 = builder.add_node(node)
        
        
        assert node_validation_1.valid is False
        assert node_validation_1.errors == [
            "Node with id 'node_id' already exists"
        ]
        assert node_validation_1.warnings == []
        assert node_validation_1.suggestions == []



    def test_update_node_success(self, tmp_path: Path):
        """Test Node Updation"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal("goal_1" , "example_goal" , "goal which does something", SuccessCriterion(
            id="sc1",
            description="Must succeed",
            metric="status",
            target="success",
        ), [],["llm"],)

        node = return_node("node_id" , "example_node", "node that does something" , ["key_1"] , ["key_2"] , ["tool_1"] , "llm_tool_use")

        assert builder.set_goal(goal).valid
        assert builder.approve("goal ok") is True
        assert builder.add_node(node).valid

        validation = builder.update_node(
            "node_id",
            name="updated_name",
            description="updated description",
        )
        assert validation.valid is True
        assert validation.errors == []

        updated_node = next(n for n in builder.session.nodes if n.id == "node_id")
        assert updated_node.name == "updated_name"
        assert updated_node.description == "updated description"
        
        

    def test_update_node_node_not_found(self, tmp_path: Path):
        """Test Node updation when node not found"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node = return_node("node_id" , "example_node", "node that does something" , ["key_1"] , ["key_2"] , ["tool_1"] , "llm_tool_use")


        assert builder.set_goal(goal).valid
        assert builder.approve("goal ok") is True
        assert builder.add_node(node).valid

        result = builder.update_node("missing_node", name="new_name")

        assert result.valid is False
        assert result.errors == ["Node 'missing_node' not found"]

    def test_update_node_empty(self , tmp_path: Path): 
        """Test Node updation when values are empty"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node = return_node("" , "", "" , [] , [] , [], "llm_tool_use")


        builder.set_goal(goal).valid
        builder.approve("goal ok") is True
        builder.add_node(node).valid


        builder.update_node("")


    def test_remove_node(self , tmp_path:Path):
        """"Test Node removal"""
        builder = GraphBuilder("graph_1", tmp_path)

        node = return_node("node_1" , "node_example" , "node that does something", ["key_1", "key_2" ] , ["key_1" , "key_2"], ["tool_1"], "llm_tool_use")

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        assert builder.set_goal(goal).valid
        assert builder.approve("goal ok") is True
        assert builder.add_node(node).valid


        validation = builder.remove_node("node_1")

        assert validation.valid is True
        assert validation.errors == []
        assert validation.warnings == []
        assert validation.suggestions == []


    def test_remove_node_fails(self, tmp_path: Path):
        """"Test Node removal failed when referenced by edge"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node_1 = return_node(
            "node_1",
            "node_1",
            "desc",
            ["a"],
            ["b"],
            ["tool_1"],
            "llm_tool_use"
        )

        node_2 = return_node(
            "node_2",
            "node_2",
            "desc",
            ["b"],
            ["c"],
            ["tool_1"],
            "llm_tool_use"
        )

        assert builder.set_goal(goal).valid
        assert builder.approve("ok") is True
        assert builder.add_node(node_1).valid
        assert builder.add_node(node_2).valid

        result = builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )
        
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.suggestions == []
        
        
        result_1 = builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )
        
        assert result_1.valid is False
        assert result_1.errors == [
            "Edge with id 'edge_1' already exists"
        ]
        assert result.warnings == []
        assert result.suggestions == []
        
        result_2 = builder.add_edge(
            EdgeSpec(
                id="",
                source="",
                target="",
            )
        )
        
        assert result_2.valid is False
        assert "Edge must have an id" in result_2.errors
        assert "Edge source '' not found in nodes" in result_2.errors
        assert "Edge target '' not found in nodes" in result_2.errors
        assert result_2.warnings == []
        assert result_2.suggestions == []

        builder.session.phase = BuildPhase.ADDING_NODES

        validation = builder.remove_node("node_1")

        assert validation.valid is False
        assert result_2.errors == [
            "Edge must have an id",
            "Edge source '' not found in nodes",
            "Edge target '' not found in nodes",
        ]


        assert any(n.id == "node_1" for n in builder.session.nodes)



    def test_validate(self , tmp_path:Path) :
        """"Test Graph Validation"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node_1 = return_node(
            "node_1",
            "node_1",
            "desc",
            ["a"],
            ["b"],
            ["tool_1"],
            "llm_tool_use"
        )

        node_2 = return_node(
            "node_2",
            "node_2",
            "desc",
            ["b"],
            ["c"],
            ["tool_1"],
            "llm_tool_use"
        )

        assert builder.set_goal(goal).valid
        assert builder.approve("ok") is True
        assert builder.add_node(node_1).valid
        assert builder.add_node(node_2).valid

        builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )

        result = builder.validate()

        assert result.suggestions == []
        assert result.valid == True
        assert result.warnings == []
        assert result.errors == []



    def test_validate_empty(self , tmp_path: Path):
        """Test Graph Validation when values are empty """
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = Goal(
        id="goal_1",
        name="example_goal",
        description="goal",
        success_criteria=[],  
        constraints=[],
        required_capabilities=[],
    )

        node_1 = return_node(
            "node_1",
            "node_1",
            "desc",
            ["a"],
            ["b"],
            ["tool_1"],
            "llm_tool_use"
        )

        node_2 = return_node(
            "node_2",
            "node_2",
            "desc",
            ["b"],
            ["c"],
            ["tool_1"],
            "llm_tool_use"
        )


        builder.session.phase=  BuildPhase.INIT
        builder.set_goal(goal).valid
        builder.approve("ok") is True
        builder.session.phase=  BuildPhase.ADDING_NODES
        builder.add_node(node_1).valid
        builder.add_node(node_2).valid

        builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )

        result = builder.validate()

        assert result.suggestions == []
        assert result.valid == True
        assert result.warnings == []
        assert result.errors == []
 

    def test_run_test_expected_output_matches(self, tmp_path: Path):
        """"Test Running of Tests with expected matches"""
        builder = setup_builder_for_run_test(tmp_path)


        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node_1 = return_node(
            "node_1",
            "node_1",
            "desc",
            ["a"],
            ["b"],
            ["tool_1"],
            "llm_tool_use"
        )

        node_2 = return_node(
            "node_2",
            "node_2",
            "desc",
            ["b"],
            ["c"],
            ["tool_1"],
            "llm_tool_use"
        )

        # Required workflow
        assert builder.set_goal(goal).valid
        assert builder.approve("ok") is True
        assert builder.add_node(node_1).valid
        assert builder.add_node(node_2).valid


        builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )

        test = TestCase(
            id="t1",
            description="desc",
            input={"x": 1},
            expected_output="ok",
            expected_contains=None,
            notes="",
        )

        fake_result = SimpleNamespace(
            success=True,
            output={"result": "ok"},
            path=["n1"],
        )

        executor = MagicMock()
        executor.execute = MagicMock(return_value=fake_result)

        result = builder.run_test(test, lambda: executor)

        assert result.test_id is 't1'
        assert result.passed is False
        assert result.actual_output is None
        assert result.error == "a coroutine was expected, got namespace(success=True, output={'result': 'ok'}, path=['n1'])"
        assert result.execution_path == []



    def test_final_approve_false(self, tmp_path: Path):
        """Test Final Approve is False"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)


        test = TestCase(
            id="t1",
            description="desc",
            input={"x": 1},
            expected_output="ok",
            expected_contains=None,
            notes="",
        )

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        assert builder   
        assert builder.set_goal(goal).valid
        assert builder.session.phase == BuildPhase.GOAL_DRAFT


        builder.session.test_cases = [test]

        approved = builder.final_approve("looks good")

        assert approved is False
        
        
        
    def test_final_approve_passed(self, tmp_path: Path):
        """Test final approve is passed"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        builder.validate = MagicMock(return_value=ValidationResult(
            valid=True,
            errors=[],
            warnings=[],
            suggestions=[],
        ))

        builder.session.test_cases = [
            TestCase(
                id="t1",
                description="test",
                input={"x": 1},
                expected_output=None,
                expected_contains=None,
                notes="",
            )
        ]

        builder.session.test_results = [
            TestResult(
                test_id="t1",
                passed=True,
                actual_output={"result": "ok"},
                execution_path=[],
            )
        ]

        builder._save_session = MagicMock()

        approved = builder.final_approve("final approval")

        assert approved is True
        assert builder.session.phase == BuildPhase.APPROVED
        assert builder.session.approvals[-1]["phase"] == "final"
        assert builder.session.approvals[-1]["comment"] == "final approval"
        
        
        
    def test_export_to_file(self, tmp_path: Path):
        """Test Export to file"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        node_1 = return_node("node_1" , "node_example" , "node that does something", ["key_1", "key_2" ] , ["key_1" , "key_2"], ["tool_1"], "llm_tool_use")

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        assert builder.set_goal(goal).valid
        assert builder.approve("ok") is True
        
        # builder.session.phase = BuildPhase.ADDING_NODES
        node_2 = return_node(
            "node_2",
            "node_example_2",
            "another node",
            ["key_2"],
            ["key_3"],
            ["tool_1"],
            "llm_tool_use",
        )

        builder.session.phase = BuildPhase.ADDING_NODES
        builder.session.nodes = [node_1, node_2]

        builder.session.phase = BuildPhase.ADDING_EDGES
        result = builder.add_edge(
            EdgeSpec(
                id="edge_1",
                source="node_1",
                target="node_2",
            )
        )
        assert result.valid


        builder.session.phase = BuildPhase.APPROVED

        fake_graph = MagicMock()
        fake_code = "print('hello')"

        builder._build_graph = MagicMock(return_value=fake_graph)
        builder._generate_code = MagicMock(return_value=fake_code)
        builder._save_session = MagicMock()

        output_path = tmp_path / "exported_graph.py"

        builder.export_to_file(output_path)

        builder._build_graph.assert_called_once()
        builder._generate_code.assert_called_once_with(fake_graph)
        builder._save_session.assert_called_once()

        assert output_path.exists()
        assert output_path.read_text() == fake_code
        assert builder.session.phase == BuildPhase.EXPORTED



    def test_show_and_status_with_goal_nodes_edges(self, tmp_path: Path):
        """Test show and status values"""
        builder = GraphBuilder("graph_1", storage_path=tmp_path)

        goal = return_goal(
            "goal_1",
            "example_goal",
            "goal description",
            SuccessCriterion(
                id="sc1",
                description="Must succeed",
                metric="status",
                target="success",
            ),
            [],
            ["llm"],
        )

        node = return_node(
            "node_1",
            "Example Node",
            "desc",
            ["a"],
            ["b"],
            ["tool_1"],
            "llm_tool_use"
        )

        edge = EdgeSpec(
            id="edge_1",
            source="node_1",
            target="node_2",
        )

        builder.session.goal = goal
        builder.session.nodes = [node]
        builder.session.edges = [edge]
        
        show_output = builder.show()
        status_output = builder.status()
        
        assert "=== Build: graph_1 ===" in show_output
        assert "Goal: example_goal" in show_output
        assert "[node_1]" in show_output
        assert "node_1 --" in show_output

        
        expected_status_output = {
        'name': 'graph_1',
        'phase': 'init',
        'goal': 'example_goal',
        'nodes': 1,
        'edges': 1,
        'tests': 0,
        'tests_passed': 0,
        'approvals': 0,
        'pending_validation': None,
        }

        assert {k: status_output[k] for k in expected_status_output} == expected_status_output


