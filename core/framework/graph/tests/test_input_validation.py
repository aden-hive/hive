
import unittest
from unittest.mock import MagicMock
from framework.graph.node import NodeProtocol, NodeContext, NodeSpec, SharedMemory, NodeResult

class MockNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True)

class TestInputValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_runtime = MagicMock()

    def test_validate_input_valid(self):
        """Test validation passes with correct inputs."""
        spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Testing validation",
            input_keys=["name", "age"],
            input_schema={
                "name": {"type": "string", "required": True},
                "age": {"type": "int", "required": True},
                "bio": {"type": "string", "required": False}
            }
        )
        
        memory = SharedMemory()
        ctx = NodeContext(
            runtime=self.mock_runtime,
            node_id="test_node",
            node_spec=spec,
            memory=memory,
            input_data={"name": "Alice", "age": 30}
        )
        
        node = MockNode()
        errors = node.validate_input(ctx)
        self.assertEqual(len(errors), 0)

    def test_validate_input_missing_required(self):
        """Test validation fails when required input is missing."""
        spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Testing validation",
            input_keys=["name"],
            input_schema={
                "name": {"type": "string", "required": True}
            }
        )
        
        memory = SharedMemory()
        ctx = NodeContext(
            runtime=self.mock_runtime,
            node_id="test_node",
            node_spec=spec,
            memory=memory,
            input_data={}  # Missing "name"
        )
        
        node = MockNode()
        errors = node.validate_input(ctx)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("Missing required input: name" in e for e in errors))

    def test_validate_input_wrong_type(self):
        """Test validation fails when input has wrong type."""
        spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Testing validation",
            input_keys=["age"],
            input_schema={
                "age": {"type": "int", "required": True}
            }
        )
        
        memory = SharedMemory()
        ctx = NodeContext(
            runtime=self.mock_runtime,
            node_id="test_node",
            node_spec=spec,
            memory=memory,
            input_data={"age": "thirty"}  # String instead of int
        )
        
        node = MockNode()
        errors = node.validate_input(ctx)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("expected int" in e for e in errors))

    def test_validate_input_optional_missing_is_ok(self):
        """Test validation passes when optional input is missing."""
        spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Testing validation",
            input_keys=["name"],
            input_schema={
                "name": {"type": "string", "required": True},
                "bio": {"type": "string", "required": False}
            }
        )
        
        memory = SharedMemory()
        ctx = NodeContext(
            runtime=self.mock_runtime,
            node_id="test_node",
            node_spec=spec,
            memory=memory,
            input_data={"name": "Alice"}  # Missing optional "bio"
        )
        
        node = MockNode()
        errors = node.validate_input(ctx)
        self.assertEqual(len(errors), 0)

    def test_validate_input_from_memory(self):
        """Test validation works when input comes from shared memory."""
        spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="Testing validation",
            input_keys=["score"],
            input_schema={
                "score": {"type": "float", "required": True}
            }
        )
        
        memory = SharedMemory()
        memory.write("score", 95.5)
        
        ctx = NodeContext(
            runtime=self.mock_runtime,
            node_id="test_node",
            node_spec=spec,
            memory=memory,
            input_data={}
        )
        
        node = MockNode()
        errors = node.validate_input(ctx)
        self.assertEqual(len(errors), 0)

if __name__ == "__main__":
    unittest.main()
