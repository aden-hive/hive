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

Tools fall into two categories based on whether they need external API credentials:

| Signature | Meaning | CI Enforcement |
|-----------|---------|----------------|
| `register_tools(mcp)` | No credentials needed | ✅ Just works |
| `register_tools(mcp, credentials=None)` | Requires credentials | ⚠️ Must have `CredentialSpec` |

**This is enforced by CI** — if your `register_tools` accepts a `credentials` parameter, every tool it registers must appear in a `CredentialSpec.tools` list. Otherwise, CI will fail with a clear error message.

### Tools WITHOUT Credentials (Simple Case)

If your tool doesn't need external API keys (file operations, local processing, etc.), just use the simple signature:

```python
def register_tools(mcp: FastMCP) -> None:
    """Register tools that don't need credentials."""

    @mcp.tool()
    def my_local_tool(path: str) -> dict:
        """Process a local file."""
        # No credentials needed - just do the work
        return {"result": process_file(path)}
```

That's it! No additional configuration needed.

### Tools WITH Credentials (Integration Case)

For tools requiring API keys, follow these steps:

#### Step 1: Add the `credentials` parameter

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    @mcp.tool()
    def my_api_tool(query: str) -> dict:
        """Tool that requires an API key."""
        # Use credentials adapter if provided, fallback to direct env access
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

#### Step 2: Create a CredentialSpec

Find the appropriate category file in `src/aden_tools/credentials/` or create a new one:

| Category | File | Examples |
|----------|------|----------|
| LLM providers | `llm.py` | anthropic, openai |
| Search tools | `search.py` | brave_search, google_search |
| Email providers | `email.py` | resend, google/gmail |
| GitHub | `github.py` | github |
| CRM | `hubspot.py` | hubspot |
| Messaging | `slack.py` | slack |

Add your credential spec:

```python
# In credentials/<category>.py
from .base import CredentialSpec

MY_CREDENTIALS = {
    "my_api": CredentialSpec(
        env_var="MY_API_KEY",
        tools=["my_api_tool"],  # IMPORTANT: List ALL tool names this credential covers
        required=True,
        help_url="https://example.com/api-keys",
        description="API key for My Service",
        # Credential store mapping
        credential_id="my_api",
        credential_key="api_key",
    ),
}
```

**Important:** The `tools` list must include every tool name that your `register_tools` function creates. CI will fail if any tool is missing.

#### Step 3: Merge into CREDENTIAL_SPECS

If you created a new category file, import and merge it in `credentials/__init__.py`:

```python
from .my_category import MY_CREDENTIALS

CREDENTIAL_SPECS = {
    **LLM_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **MY_CREDENTIALS,  # Add new category
}

__all__ = [
    # ... existing exports
    "MY_CREDENTIALS",
]
```

#### Step 4: Update register_all_tools

In `tools/__init__.py`, add your tool registration with credentials:

```python
from .my_tool import register_tools as register_my_tool

def register_all_tools(mcp: FastMCP, credentials=None) -> list[str]:
    # ... existing registrations

    # Tools that need credentials
    register_my_tool(mcp, credentials=credentials)

    return [
        # ... existing tool names
        "my_api_tool",
    ]
```

### CI Enforcement Rules

The following conformance tests run in CI (`tests/integrations/test_spec_conformance.py`):

| Test | What It Checks |
|------|----------------|
| `TestModuleStructure` | Every tool module exports `register_tools` |
| `TestRegisterToolsSignature` | Correct function signature (`mcp` param, optional `credentials`) |
| `TestCredentialSpecFields` | All CredentialSpec fields are complete (`env_var`, `help_url`, `description`, `credential_id`, `credential_key`) |
| `TestSpecToolsMatchRegistered` | Tool names in `spec.tools` actually exist |
| `TestCredentialCoverage` | **Every tool from a module with `credentials` param has a spec** |

If `TestCredentialCoverage` fails, you'll see:

```
Tool 'my_new_tool' from module 'my_tool' accepts credentials but has no CredentialSpec.

Fix by either:
  1. Adding a CredentialSpec in credentials/<category>.py with tools=['my_new_tool'], or
  2. Removing 'credentials' param from register_tools() if this tool doesn't need credentials
```

### Testing with Mock Credentials

```python
from aden_tools.credentials import CredentialStoreAdapter

def test_my_tool_with_valid_key(mcp):
    creds = CredentialStoreAdapter.for_testing({"my_api": "test-key"})
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
