# Building Tools for Aden

This guide explains how to create new tools for the Aden agent framework using FastMCP.

## Quick Start Checklist

1. Create folder under `src/aden_tools/tools/<tool_name>/`
2. Implement a `register_tools(mcp: FastMCP)` function using the `@mcp.tool()` decorator
3. Add a `README.md` documenting your tool
4. Register in `src/aden_tools/tools/__init__.py`
5. Add tests in `tests/tools/`

## Tool Structure

Each tool lives in its own folder:

```
src/aden_tools/tools/my_tool/
├── __init__.py           # Export register_tools function
├── my_tool.py            # Tool implementation
└── README.md             # Documentation
```

## Implementation Pattern

Tools use FastMCP's native decorator pattern:

```python
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register my tools with the MCP server."""

    @mcp.tool()
    def my_tool(
        query: str,
        limit: int = 10,
    ) -> dict:
        """
        Search for items matching a query.

        Use this when you need to find specific information.

        Args:
            query: The search query (1-500 chars)
            limit: Maximum number of results (1-100)

        Returns:
            Dict with search results or error dict
        """
        # Validate inputs
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}
        if limit < 1 or limit > 100:
            limit = max(1, min(100, limit))

        try:
            # Your implementation here
            results = do_search(query, limit)
            return {
                "query": query,
                "results": results,
                "total": len(results),
            }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}
```

## Exporting the Tool

In `src/aden_tools/tools/my_tool/__init__.py`:
```python
from .my_tool import register_tools

__all__ = ["register_tools"]
```

In `src/aden_tools/tools/__init__.py`, add to `_TOOL_MODULES`:
```python
_TOOL_MODULES = [
    # ... existing tools
    "my_tool",
]
```

## Credential Management

For tools requiring API keys, use the centralized `CredentialManager`. This enables:
- **Agent-aware validation**: Credentials are checked when an agent loads, not at server startup
- **Better error messages**: Users see exactly which credentials are missing and how to get them
- **Easy testing**: Use `CredentialManager.for_testing()` to mock credentials

### Adding a New Credential

1. Find the appropriate category file in `src/aden_tools/credentials/`:
   - `llm.py` - LLM providers (anthropic, openai, etc.)
   - `search.py` - Search tools (brave_search, google_search, etc.)
   - Or create a new category file for integrations

2. Add the credential spec to the category's dict:

```python
# In credentials/search.py
SEARCH_CREDENTIALS = {
    # ... existing credentials
    "my_api": CredentialSpec(
        env_var="MY_API_KEY",
        tools=["my_api_tool"],  # Which tools need this credential
        required=True,          # or False for optional
        help_url="https://example.com/api-keys",
        description="API key for My Service",
    ),
}
```

3. If you created a new category file, import and merge it in `credentials/__init__.py`:

```python
from .my_category import MY_CATEGORY_CREDENTIALS

CREDENTIAL_SPECS = {
    **LLM_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **MY_CATEGORY_CREDENTIALS,  # Add new category
}
```

4. Update your tool to accept the optional `credentials` parameter:

```python
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager


def register_tools(
    mcp: FastMCP,
    credentials: Optional["CredentialManager"] = None,
) -> None:
    @mcp.tool()
    def my_api_tool(query: str) -> dict:
        """Tool that requires an API key."""
        # Use CredentialManager if provided, fallback to direct env access
        if credentials is not None:
            api_key = credentials.get("my_api")
        else:
            api_key = os.getenv("MY_API_KEY")

        if not api_key:
            return {
                "error": "MY_API_KEY environment variable not set",
                "help": "Get an API key at https://example.com/api-keys",
            }

        # Use the API key...
```

5. Update `register_all_tools()` in `tools/__init__.py` to pass credentials to your tool.

### Testing with Mock Credentials

```python
from aden_tools.credentials import CredentialManager

def test_my_tool_with_valid_key(mcp):
    creds = CredentialManager.for_testing({"my_api": "test-key"})
    register_tools(mcp, credentials=creds)
    tool_fn = mcp._tool_manager._tools["my_api_tool"].fn

    result = tool_fn(query="test")
    # Assertions...
```

### When Validation Happens

Credentials are validated when an agent is loaded (via `AgentRunner.validate()`), not at MCP server startup. This means:

1. The MCP server always starts (even if credentials are missing)
2. When you load an agent, validation checks which tools it needs
3. If credentials are missing, you get a clear error:

```
Cannot run agent: Missing credentials

The following tools require credentials that are not set:

  web_search requires BRAVE_SEARCH_API_KEY
    API key for Brave Search
    Get an API key at: https://brave.com/search/api/
    Set via: export BRAVE_SEARCH_API_KEY=your_key

Set these environment variables and re-run the agent.
```

## Environment Variables (Legacy)

For simple cases or backward compatibility, you can still check environment variables directly:

```python
import os

def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def my_api_tool(query: str) -> dict:
        """Tool that requires an API key."""
        api_key = os.getenv("MY_API_KEY")
        if not api_key:
            return {
                "error": "MY_API_KEY environment variable not set",
                "help": "Get an API key at https://example.com/api",
            }

        # Use the API key...
```

However, using `CredentialManager` is recommended for new tools as it provides better validation and testing support.

## Best Practices

### Error Handling

Return error dicts instead of raising exceptions:

```python
@mcp.tool()
def my_tool(**kwargs) -> dict:
    try:
        result = do_work()
        return {"success": True, "data": result}
    except SpecificError as e:
        return {"error": f"Failed to process: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}
```

### Return Values

- Return dicts for structured data
- Include relevant metadata (query, total count, etc.)
- Use `{"error": "message"}` for errors

### Documentation

The docstring becomes the tool description in MCP. Include:
- What the tool does
- When to use it
- Args with types and constraints
- What it returns

Every tool folder needs a `README.md` with:
- Description and use cases
- Usage examples
- Argument table
- Environment variables (if any)
- Error handling notes

## Testing

Place tests in `tests/tools/test_{{tool_name}}.py`:

```python
import pytest
from fastmcp import FastMCP

from aden_tools.tools.{{tool_name}} import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with tools registered."""
    server = FastMCP("test")
    register_tools(server)
    return server


def test_my_tool_basic(mcp):
    """Test basic tool functionality."""
    tool_fn = mcp._tool_manager._tools["my_tool"].fn
    result = tool_fn(query="test")
    assert "results" in result


def test_my_tool_validation(mcp):
    """Test input validation."""
    tool_fn = mcp._tool_manager._tools["my_tool"].fn
    result = tool_fn(query="")
    assert "error" in result
```

Mock external APIs to keep tests fast and deterministic.

## Naming Conventions

- **Folder name**: `snake_case` with `_tool` suffix (e.g., `file_read_tool`)
- **Function name**: `snake_case` (e.g., `file_read`)
- **Tool description**: Clear, actionable docstring
