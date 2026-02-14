# Browser-Use Tool

The `browser-use` tool provides natural language web automation capabilities. It allows agents to interact with websites as a human would—clicking buttons, filling out forms, and navigating complex page structures.

## Features
- **Natural Language Execution**: Describe what you want to do on the web in plain English.
- **Dynamic Content Support**: Handles JavaScript-rendered pages and SPAs seamlessly.
- **Agent-Driven**: Autonomous decision-making to achieve the requested goal.
- **Security**: Built-in SSRF protection and resource limits.

## Configuration
Requires an `OPENAI_API_KEY` (or configured via the Aden credential store).

## Usage
```python
from aden_tools.tools import register_all_tools
from fastmcp import FastMCP

mcp = FastMCP("my-server")
register_all_tools(mcp)
```

### Tool: `browser_use_task`
Executes a multi-step web task.

**Arguments**:
- `task`: The natural language description of the task.
- `allowed_domains`: Optional list of domains the agent is restricted to.
- `max_steps`: Maximum number of steps (default 15).
- `timeout`: Maximum runtime in seconds (default 60).
- `headless`: Whether to run without a visible browser window (default True).
