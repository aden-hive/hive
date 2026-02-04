import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add core to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from framework.runner.runner import AgentRunner
from framework.graph import Goal, GraphSpec, NodeSpec

class TestValidationStrict(unittest.TestCase):
    def setUp(self):
        # Mock GraphSpec
        self.graph = MagicMock(spec=GraphSpec)
        self.graph.id = "test-agent"
        self.graph.description = "Test Agent"
        self.graph.validate.return_value = []
        self.graph.nodes = []
        self.graph.edges = []
        self.graph.async_entry_points = []
        self.graph.has_async_entry_points.return_value = False
        self.graph.entry_node = "n1"
        self.graph.terminal_nodes = ["n1"]
        
        # Mock Goal
        self.goal = MagicMock(spec=Goal)
        self.goal.name = "Test Goal"
        self.goal.description = "Test Goal Description"
        self.goal.success_criteria = [MagicMock()]
        self.goal.constraints = []
        
        # Initialize runner with mocks
        self.runner = AgentRunner(
            agent_path=Path("/tmp/test_agent"),
            graph=self.graph,
            goal=self.goal,
            mock_mode=True
        )

    def test_validate_strict_missing_tools(self):
        """Test validate(strict=True) fails when tools are missing."""
        # Setup node requiring a missing tool
        node = MagicMock(spec=NodeSpec)
        node.id = "n1"
        node.name = "task"
        node.description = "desc"
        node.node_type = "task"
        node.input_keys = []
        node.output_keys = []
        node.tools = ["missing_tool"]
        self.graph.nodes = [node]
        
        # Act
        result = self.runner.validate(strict=True)
        
        # Assert
        self.assertFalse(result.valid, "Validation should fail in strict mode with missing tools")
        self.assertIn("missing_tool", result.missing_tools)

    def test_validate_default_missing_tools(self):
        """Test validate(strict=False) preserves default behavior (valid=True)."""
        # Setup node requiring a missing tool
        node = MagicMock(spec=NodeSpec)
        node.id = "n1"
        node.name = "task"
        node.description = "desc"
        node.node_type = "task"
        node.input_keys = []
        node.output_keys = []
        node.tools = ["missing_tool"]
        self.graph.nodes = [node]
        
        # Act
        # Default strict=False
        result = self.runner.validate()
        
        # Assert
        self.assertTrue(result.valid, "Validation should pass in default mode logic checks")
        self.assertIn("missing_tool", result.missing_tools)
        # Check warnings for the missing tool message
        self.assertTrue(any("Missing tool implementations" in w for w in result.warnings))

if __name__ == "__main__":
    unittest.main()
