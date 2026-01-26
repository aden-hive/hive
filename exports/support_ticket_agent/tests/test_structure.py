import unittest
import json
import os

class TestSupportTicketAgent(unittest.TestCase):
    def setUp(self):
        # Locate the agent.json file relative to this test file
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.agent_path = os.path.join(self.current_dir, "../agent.json")

    def test_agent_json_exists(self):
        """Check if agent.json exists"""
        self.assertTrue(os.path.exists(self.agent_path), "agent.json file is missing")

    def test_agent_structure(self):
        """Validate the JSON keys"""
        with open(self.agent_path, 'r') as f:
            data = json.load(f)
        
        # Check Critical Keys
        self.assertIn("goal", data)
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        
        # Check Logic Consistency
        self.assertEqual(data["goal"]["goal_id"], "support_ticket")
        
        # Verify Node Connections
        node_ids = [node["node_id"] for node in data["nodes"]]
        self.assertIn("analyze", node_ids)

if __name__ == "__main__":
    unittest.main()