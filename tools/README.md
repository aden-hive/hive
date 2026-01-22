# Aden Tools

Tool library for the Aden agent framework. Provides a collection of tools that AI agents can use to interact with external systems, process data, and perform actions via the Model Context Protocol (MCP).

## Installation

```bash
pip install -e tools
```

For development:

```bash
pip install -e "tools[dev]"
```

## Environment Setup

Some tools require API keys to function. Copy the example file and add your credentials:

```bash
cp .env.example .env
```

| Variable               | Required For                  | Get Key                                                 |
| ---------------------- | ----------------------------- | ------------------------------------------------------- |
| `ANTHROPIC_API_KEY`    | MCP server startup, LLM nodes | [console.anthropic.com](https://console.anthropic.com/) |
| `BRAVE_SEARCH_API_KEY` | `web_search` tool             | [brave.com/search/api](https://brave.com/search/api/)   |

Alternatively, export as environment variables:

```bash
export ANTHROPIC_API_KEY=your-key-here
export BRAVE_SEARCH_API_KEY=your-key-here
```

See [.env.example](.env.example) for details.

## Quick Start

### As an MCP Server

```python
from fastmcp import FastMCP
from aden_tools.tools import register_all_tools

mcp = FastMCP("tools")
register_all_tools(mcp)
mcp.run()
```

Or run directly:

```bash
python mcp_server.py
```

## Available Tools

| Tool           | Description                              |
| -------------- | ---------------------------------------- |
| `example_tool` | Template tool demonstrating the pattern  |
| `file_read`    | Read contents of local files             |
| `file_write`   | Write content to local files             |
| `web_search`   | Search the web using Brave Search API    |
| `web_scrape`   | Scrape and extract content from webpages |
| `pdf_read`     | Read and extract text from PDF files     |

## Project Structure

```
tools/
├── src/aden_tools/
│   ├── __init__.py          # Main exports
│   ├── utils/               # Utility functions
│   └── tools/               # Tool implementations
│       ├── example_tool/
│       ├── file_read_tool/
│       ├── file_write_tool/
│       ├── web_search_tool/
│       ├── web_scrape_tool/
│       └── pdf_read_tool/
├── tests/                   # Test suite
├── mcp_server.py            # MCP server entry point
├── README.md
├── BUILDING_TOOLS.md        # Tool development guide
└── pyproject.toml
```

## Creating Custom Tools

Tools use FastMCP's native decorator pattern:

```python
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def my_tool(query: str, limit: int = 10) -> dict:
        """
        Search for items matching the query.

        Args:
            query: The search query
            limit: Max results to return

        Returns:
            Dict with results or error
        """
        try:
            results = do_search(query, limit)
            return {"results": results, "total": len(results)}
        except Exception as e:
            return {"error": str(e)}
```

See [BUILDING_TOOLS.md](BUILDING_TOOLS.md) for the full guide.

## Documentation

- [Building Tools Guide](BUILDING_TOOLS.md) - How to create new tools
- Individual tool READMEs in `src/aden_tools/tools/*/README.md`

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](../LICENSE) file for details.
