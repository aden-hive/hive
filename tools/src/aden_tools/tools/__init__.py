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

from typing import TYPE_CHECKING, Optional

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager

# Import register_tools from each tool module
from .csv_tool import register_tools as register_csv
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
from .pdf_read_tool import register_tools as register_pdf_read
from .web_scrape_tool import register_tools as register_web_scrape
from .web_search_tool import register_tools as register_web_search

# [NEW] Import Stripe tool
from .stripe_tool import register_tools as register_stripe

# [NEW] Import Zoom tool
from .meeting_tool import register_tools as register_meeting_tools


def register_all_tools(
    mcp: FastMCP,
    credentials: Optional["CredentialManager"] = None,
) -> list[str]:
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
    register_web_scrape(mcp)
    register_pdf_read(mcp)

    # Tools that need credentials (pass credentials if provided)
    # web_search supports multiple providers (Google, Brave) with auto-detection
    register_web_search(mcp, credentials=credentials)
    
    # [NEW] Register Stripe tool
    register_stripe(mcp, credentials=credentials)

    # [NEW] Register Zoom tool
  
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
        # [NEW] Stripe Functions
        "get_customer_by_email",
        "create_customer",
        "update_customer",
        "list_customers",
        "get_customer_by_id",
        "get_subscription_status",
        "create_subscription",
        "update_subscription",
        "cancel_subscription",
        "list_subscriptions",
        "list_invoices",
        "retrieve_invoice",
        "pay_invoice",
        "list_payment_intents",
        "create_checkout_session",
        "create_payment_link",
        "verify_webhook_signature",
       
    ]


__all__ = ["register_all_tools"]