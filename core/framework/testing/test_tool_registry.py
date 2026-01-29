# test_tool_registry.py
import sys
import logging
from pathlib import Path
from framework.runner.tool_registry import ToolRegistry

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_mcp_server_registration():
    """Test MCP server registration and tool discovery."""
    registry = ToolRegistry()

    # In test_tool_registry.py, update the server_config to:
    server_config = {
        "name": "test_server",
        "transport": "http",
        "url": "http://localhost:8000",  # Make sure this matches your server's port
        "description": "Test MCP Server",
        "api_version":"v1"
    }

    try:
        # Register the MCP server
        result = registry.register_mcp_server(server_config)
        logger.info(f"Registration result: {result}")

        if not result['success']:
            logger.error(f"Failed to register MCP server: {result.get('error')}")
            return False

        # List registered tools
        tools = registry.get_tools()
        logger.info(f"Registered tools: {list(tools.keys())}")

        # Test tool execution if tools are available
        if tools:
            tool_name = next(iter(tools))
            logger.info(f"Testing tool: {tool_name}")

            # Get the executor
            executor = registry.get_executor()

            # Create a test tool use
            from framework.llm.provider import ToolUse
            tool_use = ToolUse(
                id="test_call_1",
                name=tool_name,
                input={"test": "value"}  # Update with appropriate input
            )

            # Execute the tool
            result = executor(tool_use)
            logger.info(f"Tool execution result: {result}")

        return True

    except Exception as e:
        logger.exception("Test failed with exception")
        return False
    finally:
        # Clean up
        registry.cleanup()

if __name__ == "__main__":
    success = test_mcp_server_registration()
    sys.exit(0 if success else 1)
