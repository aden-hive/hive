"""
Aden Tools - Tool implementations for FastMCP.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialManager

    mcp = FastMCP("my-server")
    credentials = CredentialManager()
    register_all_tools(mcp, credentials=credentials)
"""
from typing import List, Optional, TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager

# Import register_tools from each tool module
from .example_tool import register_tools as register_example
from .web_search_tool import register_tools as register_web_search
from .web_scrape_tool import register_tools as register_web_scrape
from .pdf_read_tool import register_tools as register_pdf_read

# Import file system toolkits
from .file_system_toolkits.view_file import register_tools as register_view_file
from .file_system_toolkits.write_to_file import register_tools as register_write_to_file
from .file_system_toolkits.list_dir import register_tools as register_list_dir
from .file_system_toolkits.replace_file_content import register_tools as register_replace_file_content
from .file_system_toolkits.apply_diff import register_tools as register_apply_diff
from .file_system_toolkits.apply_patch import register_tools as register_apply_patch
from .file_system_toolkits.grep_search import register_tools as register_grep_search
from .file_system_toolkits.execute_command_tool import register_tools as register_execute_command


def register_all_tools(
    mcp: FastMCP,
    credentials: Optional["CredentialManager"] = None,
) -> List[str]:
    """
    Register all tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialManager for centralized credential access.
                     If not provided, tools fall back to direct os.getenv() calls.

    Returns:
        List of registered tool names
    """
    # Tools that don't need credentials
    register_example(mcp)
    register_web_search(mcp)
    register_web_scrape(mcp)
    register_pdf_read(mcp)

    # Tools that need credentials (pass credentials if provided)
    register_web_search(mcp, credentials=credentials)

    # Register file system toolkits
    register_view_file(mcp)
    register_write_to_file(mcp)
    register_list_dir(mcp)
    register_replace_file_content(mcp)
    register_apply_diff(mcp)
    register_apply_patch(mcp)
    register_grep_search(mcp)
    register_execute_command(mcp)

    return [
        "example_tool",
        "web_search",
        "web_scrape",
        "pdf_read",
        "view_file",
        "write_to_file",
        "list_dir",
        "replace_file_content",
        "apply_diff",
        "apply_patch",
        "grep_search",
        "execute_command_tool",
    ]


__all__ = ["register_all_tools"]
