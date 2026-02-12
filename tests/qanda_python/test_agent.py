"""Unit tests for the Q&A Agent."""

import unittest
from unittest.mock import MagicMock, patch
import asyncio
from pathlib import Path

from exports.qanda_python.agent import QandAAgent
from framework.graph.executor import ExecutionResult

class TestQandAAgent(unittest.TestCase):
    """Test suite for the QandAAgent class."""

    def setUp(self):
        """Sets up the test environment by creating a QandAAgent instance."""
        self.agent = QandAAgent()

    def test_agent_initialization(self):
        """Verifies that the agent is initialized with correct metadata and goal."""
        self.assertIsNotNone(self.agent.goal)
        self.assertEqual(self.agent.goal.id, "q_and_a_goal")
        self.assertEqual(len(self.agent.nodes), 1)
        self.assertEqual(self.agent.nodes[0].id, "generate_answer")

    def test_agent_validation(self):
        """Verifies that the agent's graph structure is valid."""
        validation_result = self.agent.validate()
        self.assertTrue(validation_result["valid"])
        self.assertEqual(len(validation_result["errors"]), 0)

    def test_agent_info(self):
        """Verifies that the info() method returns correct agent details."""
        info = self.agent.info()
        self.assertEqual(info["name"], "Q&A Agent (Python)")
        self.assertEqual(info["version"], "1.0.0")
        self.assertIn("generate_answer", info["nodes"])

    @patch('exports.qanda_python.agent.GraphExecutor')
    def test_agent_setup(self, mock_executor_class):
        """Verifies that the agent's setup correctly initializes the executor."""
        mock_executor = MagicMock()
        mock_executor_class.return_value = mock_executor
        
        executor = self.agent._setup()
        
        self.assertIsNotNone(self.agent._executor)
        self.assertEqual(executor, mock_executor)
        self.assertIsNotNone(self.agent._graph)
        self.assertIsNotNone(self.agent._event_bus)
        self.assertIsNotNone(self.agent._tool_registry)

    def test_start_stop(self):
        """Verifies that start() and stop() methods manage resources correctly."""
        with patch.object(self.agent, '_setup') as mock_setup:
            asyncio.run(self.agent.start())
            mock_setup.assert_called_once()
            
        asyncio.run(self.agent.stop())
        self.assertIsNone(self.agent._executor)
        self.assertIsNone(self.agent._event_bus)

if __name__ == "__main__":
    unittest.main()
