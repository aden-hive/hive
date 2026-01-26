#!/usr/bin/env python3
"""
Example: Integrating MCP Servers with the Core Framework

This example demonstrates how to:
1. Register MCP servers programmatically
2. Use MCP tools in agents
3. Load MCP servers from configuration files
"""

import asyncio
from pathlib import Path

from framework.runner.runner import AgentRunner


async def example_1_programmatic_registration():
    """Example 1: Register MCP server programmatically"""
    print("\n=== Example 1: Programmatic MCP Server Registration ===\n")

    # Load an existing agent
    runner = AgentRunner.load("exports/task-planner")

    # Register tools MCP server via STDIO
    num_tools = runner.register_mcp_server(
        name="tools",
        transport="stdio",
        command="python",
        args=["-m", "aden_tools.mcp_server", "--stdio"],
        cwd="../tools",
    )

    print(f"Registered {num_tools} tools from tools MCP server")

    # List all available tools
    tools = runner._tool_registry.get_tools()
    print(f"\nAvailable tools: {list(tools.keys())}")

    # Run the agent with MCP tools available
    result = await runner.run({
        "objective": "Search for 'Claude AI' and summarize the top 3 results"
    })

    print(f"\nAgent result: {result}")

    # Cleanup
    runner.cleanup()


async def example_2_http_transport():
    """Example 2: Connect to MCP server via HTTP"""
    print("\n=== Example 2: HTTP MCP Server Connection ===\n")

    # First, start the tools MCP server in HTTP mode:
    # cd tools && python mcp_server.py --port 4001

    runner = AgentRunner.load("exports/task-planner")

    # Register tools via HTTP
    num_tools = runner.register_mcp_server(
        name="tools-http",
        transport="http",
        url="http://localhost:4001",
    )

    print(f"Registered {num_tools} tools from HTTP MCP server")

    # Cleanup
    runner.cleanup()


async def example_3_config_file():
    """Example 3: Load MCP servers from configuration file"""
    print("\n=== Example 3: Load from Configuration File ===\n")

    # Create a test agent folder with mcp_servers.json
    test_agent_path = Path("exports/task-planner")

    # Copy example config (in practice, you'd place this in your agent folder)
    import shutil
    shutil.copy(
        "examples/mcp_servers.json",
        test_agent_path / "mcp_servers.json"
    )

    # Load agent - MCP servers will be auto-discovered
    runner = AgentRunner.load(test_agent_path)

    # Tools are automatically available
    tools = runner._tool_registry.get_tools()
    print(f"Available tools: {list(tools.keys())}")

    # Cleanup
    runner.cleanup()

    # Clean up the test config
    (test_agent_path / "mcp_servers.json").unlink()


async def example_4_custom_agent_with_mcp_tools():
    """Example 4: Build custom agent that uses MCP tools"""
    print("\n=== Example 4: Custom Agent with MCP Tools ===\n")

    from framework.builder.workflow import WorkflowBuilder

    # Create a workflow builder
    builder = WorkflowBuilder()

    # Define goal
    builder.set_goal(
        goal_id="web-researcher",
        name="Web Research Agent",
        description="Search the web and summarize findings"
    )

    # Add success criteria
    builder.add_success_criterion(
        "search-results",
        "Successfully retrieve at least 3 web search results"
    )
    builder.add_success_criterion(
        "summary",
        "Provide a clear, concise summary of the findings"
    )

    # Add nodes that will use MCP tools
    builder.add_node(
        node_id="web-searcher",
        name="Web Search",
        description="Search the web for information",
        node_type="llm_tool_use",
        system_prompt="Search for {query} and return the top results. Use the web_search tool.",
        tools=["web_search"],  # This tool comes from tools MCP server
        input_keys=["query"],
        output_keys=["search_results"],
    )

    builder.add_node(
        node_id="summarizer",
        name="Summarize Results",
        description="Summarize the search results",
        node_type="llm_generate",
        system_prompt="Summarize the following search results in 2-3 sentences: {search_results}",
        input_keys=["search_results"],
        output_keys=["summary"],
    )

    # Connect nodes
    builder.add_edge("web-searcher", "summarizer")

    # Set entry point
    builder.set_entry("web-searcher")
    builder.set_terminal("summarizer")

    # Export the agent
    export_path = Path("exports/web-research-agent")
    export_path.mkdir(parents=True, exist_ok=True)
    builder.export(export_path)

    # Load and register MCP server
    runner = AgentRunner.load(export_path)
    runner.register_mcp_server(
        name="tools",
        transport="stdio",
        command="python",
        args=["-m", "aden_tools.mcp_server", "--stdio"],
        cwd="../tools",
    )

    # Run the agent
    result = await runner.run({"query": "latest AI breakthroughs 2026"})

    print(f"\nAgent completed with result:\n{result}")

    # Cleanup
    runner.cleanup()


async def main():
    """Run all examples"""
    print("=" * 60)
    print("MCP Integration Examples")
    print("=" * 60)

    try:
        # Run examples
        await example_1_programmatic_registration()
        # await example_2_http_transport()  # Requires HTTP server running
        # await example_3_config_file()
        # await example_4_custom_agent_with_mcp_tools()

    except Exception as e:
        print(f"\nError running example: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
