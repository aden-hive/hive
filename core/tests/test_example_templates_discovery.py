"""Test agent discovery for example templates.

Regression test to ensure that example agent templates are properly discovered
with correct metadata, especially tool_count > 0. This prevents regressions
where missing agent.json manifests cause the discovery system to fall back to
incomplete AST parsing, resulting in tool_count = 0.

See: https://github.com/aden-hive/hive/issues/6272
"""

from pathlib import Path

import pytest

from framework.agents.discovery import discover_agents


class TestExampleTemplatesDiscovery:
    """Test that example agent templates are discovered with proper metadata."""

    def test_email_reply_agent_discovered(self):
        """Test that email_reply_agent template is discovered."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        agents_by_name = {entry.name.lower().replace(" ", "_"): entry for entry in examples}
        assert "email_reply_agent" in agents_by_name, (
            f"email_reply_agent not found. Available examples: {list(agents_by_name.keys())}"
        )

    def test_meeting_scheduler_discovered(self):
        """Test that meeting_scheduler template is discovered."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        agents_by_name = {entry.name.lower().replace(" ", "_"): entry for entry in examples}
        assert "meeting_scheduler" in agents_by_name, (
            f"meeting_scheduler not found. Available examples: {list(agents_by_name.keys())}"
        )

    def test_email_reply_agent_has_tools(self):
        """Test that email_reply_agent has correct tool_count > 0."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        agents_by_name = {entry.name.lower().replace(" ", "_"): entry for entry in examples}
        entry = agents_by_name.get("email_reply_agent")
        
        assert entry is not None, "email_reply_agent not found"
        assert entry.tool_count > 0, (
            f"email_reply_agent has tool_count={entry.tool_count}, expected > 0. "
            "This suggests agent.json is missing or malformed."
        )

    def test_meeting_scheduler_has_tools(self):
        """Test that meeting_scheduler has correct tool_count > 0."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        agents_by_name = {entry.name.lower().replace(" ", "_"): entry for entry in examples}
        entry = agents_by_name.get("meeting_scheduler")
        
        assert entry is not None, "meeting_scheduler not found"
        assert entry.tool_count > 0, (
            f"meeting_scheduler has tool_count={entry.tool_count}, expected > 0. "
            "This suggests agent.json is missing or malformed."
        )

    def test_email_reply_agent_expected_tools(self):
        """Test that email_reply_agent declares expected Gmail tools."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        # agents_by_path = {str(entry.path): entry for entry in examples}
        
        # Find by exact path match
        examples_dir = Path("examples/templates")
        expected_path = examples_dir / "email_reply_agent"
        
        matching = [e for e in examples if "email_reply_agent" in str(e.path)]
        assert matching, "email_reply_agent not found in Examples"
        
        entry = matching[0]
        expected_tools = {"gmail_list_messages", "gmail_get_message", "gmail_batch_get_messages", 
                         "gmail_reply_email"}
        actual_tools = set(entry.tools)
        missing = expected_tools - actual_tools
        assert not missing, f"Missing expected tools: {missing}"

    def test_meeting_scheduler_expected_tools(self):
        """Test that meeting_scheduler declares expected calendar/sheets tools."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        matching = [e for e in examples if "meeting_scheduler" in str(e.path)]
        assert matching, "meeting_scheduler not found in Examples"
        
        entry = matching[0]
        expected_tools = {"calendar_check_availability", "calendar_list_events", 
                         "calendar_create_event", "google_sheets_get_spreadsheet",
                         "google_sheets_create_spreadsheet", "google_sheets_append_values",
                         "send_email"}
        assert entry.tool_count >= len(expected_tools), (
            f"meeting_scheduler tool_count={entry.tool_count}, expected >= {len(expected_tools)}. "
            f"Expected tools: {expected_tools}"
        )

    def test_example_templates_have_node_count(self):
        """Test that both example templates report node_count > 0."""
        groups = discover_agents()
        examples = groups.get("Examples", [])
        
        template_names = {"email_reply_agent", "meeting_scheduler"}
        
        for entry in examples:
            entry_name = entry.name.lower().replace(" ", "_")
            if entry_name in template_names:
                assert entry.node_count > 0, (
                    f"{entry.name} has node_count={entry.node_count}, expected > 0"
                )
