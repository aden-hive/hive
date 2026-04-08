import unittest
from unittest.mock import MagicMock, patch
import sys
import argparse
from pathlib import Path
import io

# Import the module under test
# Note: Adjust the import path if necessary based on how tests are run
from framework.runner import cli

class TestCli(unittest.TestCase):
    
    def setUp(self):
        # Create a dummy arguments object
        self.args = argparse.Namespace()
        self.args.json = False
        self.args.agent_path = "/tmp/dummy_agent"
        self.args.directory = "/tmp/agents"
        self.args.quiet = False
        self.args.verbose = False
    
    @patch('framework.runner.AgentRunner')
    def test_cmd_info_success(self, mock_runner_cls):
        # Setup mock
        mock_runner = MagicMock()
        mock_runner_cls.load.return_value = mock_runner
        
        mock_info = MagicMock()
        mock_info.name = "Test Agent"
        mock_info.description = "A test agent"
        mock_info.goal_name = "Test Goal"
        mock_info.goal_description = "Do something"
        mock_info.node_count = 5
        mock_info.nodes = [{"id": "start", "name": "Start", "input_keys": [], "output_keys": []}]
        mock_info.edges = []
        mock_info.success_criteria = []
        mock_info.constraints = []
        mock_info.required_tools = ["tool1"]
        mock_info.has_tools_module = True
        
        mock_runner.info.return_value = mock_info
        
        # Capture stdout
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            ret = cli.cmd_info(self.args)
            
        # Assertions
        self.assertEqual(ret, 0)
        output = mock_stdout.getvalue()
        self.assertIn("Agent: Test Agent", output)
        self.assertIn("Goal: Test Goal", output)
        
        # Verify cleanup was called
        mock_runner.cleanup.assert_called_once()
        
    @patch('framework.runner.AgentRunner')
    def test_cmd_info_file_not_found(self, mock_runner_cls):
        # Setup mock to raise FileNotFoundError
        mock_runner_cls.load.side_effect = FileNotFoundError("Agent not found")
        
        # Capture stderr
        with patch('sys.stderr', new_callable=io.StringIO) as mock_stderr:
            ret = cli.cmd_info(self.args)
            
        self.assertEqual(ret, 1)
        self.assertIn("Error: Agent not found", mock_stderr.getvalue())

    @patch('framework.runner.AgentRunner')
    def test_cmd_validate_success(self, mock_runner_cls):
        mock_runner = MagicMock()
        mock_runner_cls.load.return_value = mock_runner
        
        mock_validation = MagicMock()
        mock_validation.valid = True
        mock_validation.errors = []
        mock_validation.warnings = []
        mock_validation.missing_tools = []
        
        mock_runner.validate.return_value = mock_validation
        
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            ret = cli.cmd_validate(self.args)
            
        self.assertEqual(ret, 0)
        self.assertIn("Agent is valid", mock_stdout.getvalue())
        mock_runner.cleanup.assert_called_once()
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.iterdir')
    @patch('framework.runner.AgentRunner')
    def test_cmd_list_agents(self, mock_runner_cls, mock_iterdir, mock_exists):
        # Setup filesystem mocks
        mock_exists.return_value = True
        
        # Mock directory structure
        agent_dir_1 = MagicMock(spec=Path)
        agent_dir_1.is_dir.return_value = True
        agent_dir_1.__str__.return_value = "/tmp/agents/agent1"
        # Mock agent.json existence for this dir
        agent_json_1 = MagicMock(spec=Path)
        agent_json_1.exists.return_value = True
        agent_dir_1.__truediv__.return_value = agent_json_1
        
        mock_iterdir.return_value = [agent_dir_1]
        
        # Setup Runner mock
        mock_runner = MagicMock()
        mock_runner_cls.load.return_value = mock_runner
        
        mock_info = MagicMock()
        mock_info.name = "Agent 1"
        mock_info.description = "Desc 1"
        mock_info.node_count = 3
        mock_info.required_tools = []
        mock_runner.info.return_value = mock_info
        
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            ret = cli.cmd_list(self.args)
            
        self.assertEqual(ret, 0)
        self.assertIn("Agent 1", mock_stdout.getvalue())
        mock_runner.cleanup.assert_called_once()
