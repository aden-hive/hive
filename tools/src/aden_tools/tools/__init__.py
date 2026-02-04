"""
Aden Tools - Tool implementations for FastMCP.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialStoreAdapter

    mcp = FastMCP("my-server")
    credentials = CredentialStoreAdapter.default()
    register_all_tools(mcp, credentials=credentials)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Import register_tools from each tool module
from .csv_tool import register_tools as register_csv
from .email_tool import register_tools as register_email
from .example_tool import register_tools as register_example
from .file_system_toolkits.apply_diff import register_tools as register_apply_diff
from .file_system_toolkits.apply_patch import register_tools as register_apply_patch
from .file_system_toolkits.execute_command_tool import (
    register_tools as register_execute_command,
)
from .file_system_toolkits.grep_search import register_tools as register_grep_search
from .file_system_toolkits.list_dir import register_tools as register_list_dir
from .file_system_toolkits.replace_file_content import (
    register_tools as register_replace_file_content,
)

# Import file system toolkits
from .file_system_toolkits.view_file import register_tools as register_view_file
from .file_system_toolkits.write_to_file import register_tools as register_write_to_file
from .github_tool import register_tools as register_github
from .hubspot_tool import register_tools as register_hubspot
from .pdf_read_tool import register_tools as register_pdf_read
from .web_scrape_tool import register_tools as register_web_scrape
from .web_search_tool import register_tools as register_web_search


def register_all_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> list[str]:
    """
    Register all tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter instance.
                     If not provided, tools fall back to direct os.getenv() calls.

    Returns:
        List of registered tool names
    """
    # Tools that don't need credentials
    register_example(mcp)
    register_web_scrape(mcp)
    register_pdf_read(mcp)

    # Tools that need credentials (pass credentials if provided)
    # web_search supports multiple providers (Google, Brave) with auto-detection
    register_web_search(mcp, credentials=credentials)
    register_github(mcp, credentials=credentials)
    # email supports multiple providers (Resend) with auto-detection
    register_email(mcp, credentials=credentials)
    register_hubspot(mcp, credentials=credentials)

    # Register file system toolkits
    register_view_file(mcp)
    register_write_to_file(mcp)
    register_list_dir(mcp)
    register_replace_file_content(mcp)
    register_apply_diff(mcp)
    register_apply_patch(mcp)
    register_grep_search(mcp)
    register_execute_command(mcp)
    register_csv(mcp)

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
        "csv_read",
        "csv_write",
        "csv_append",
        "csv_info",
        "csv_sql",
        "github_list_repos",
        "github_get_repo",
        "github_search_repos",
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_list_pull_requests",
        "github_get_pull_request",
        "github_create_pull_request",
        "github_search_code",
        "github_list_branches",
        "github_get_branch",
        "github_list_stargazers",
        "github_get_user_profile",
        "github_get_user_emails",
        "send_email",
        "send_budget_alert_email",
        "hubspot_search_contacts",
        "hubspot_get_contact",
        "hubspot_create_contact",
        "hubspot_update_contact",
        "hubspot_search_companies",
        "hubspot_get_company",
        "hubspot_create_company",
        "hubspot_update_company",
        "hubspot_search_deals",
        "hubspot_get_deal",
        "hubspot_create_deal",
        "hubspot_update_deal",
    ]


__all__ = ["register_all_tools"]
