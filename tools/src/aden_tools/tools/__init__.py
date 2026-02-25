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
from .account_info_tool import register_tools as register_account_info
from .apollo_tool import register_tools as register_apollo
from .arxiv_tool import register_tools as register_arxiv
from .bigquery_tool import register_tools as register_bigquery
from .brevo_tool import register_tools as register_brevo
from .calcom_tool import register_tools as register_calcom
from .calendar_tool import register_tools as register_calendar
from .csv_tool import register_tools as register_csv
from .discord_tool import register_tools as register_discord

# Security scanning tools
from .dns_security_scanner import register_tools as register_dns_security_scanner
from .email_tool import register_tools as register_email
from .exa_search_tool import register_tools as register_exa_search
from .example_tool import register_tools as register_example
from .excel_tool import register_tools as register_excel
from .file_system_toolkits.apply_diff import register_tools as register_apply_diff
from .file_system_toolkits.apply_patch import register_tools as register_apply_patch
from .file_system_toolkits.data_tools import register_tools as register_data_tools
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
from .gmail_tool import register_tools as register_gmail
from .google_docs_tool import register_tools as register_google_docs
from .google_maps_tool import register_tools as register_google_maps
from .http_headers_scanner import register_tools as register_http_headers_scanner
from .hubspot_tool import register_tools as register_hubspot
from .news_tool import register_tools as register_news
from .pdf_read_tool import register_tools as register_pdf_read
from .port_scanner import register_tools as register_port_scanner
from .postgres_tool import register_tools as register_postgres
from .razorpay_tool import register_tools as register_razorpay
from .risk_scorer import register_tools as register_risk_scorer
from .runtime_logs_tool import register_tools as register_runtime_logs
from .serpapi_tool import register_tools as register_serpapi
from .slack_tool import register_tools as register_slack
from .ssl_tls_scanner import register_tools as register_ssl_tls_scanner
from .stripe_tool import register_tools as register_stripe
from .subdomain_enumerator import register_tools as register_subdomain_enumerator
from .tech_stack_detector import register_tools as register_tech_stack_detector
from .telegram_tool import register_tools as register_telegram
from .time_tool import register_tools as register_time
from .vision_tool import register_tools as register_vision
from .web_scrape_tool import register_tools as register_web_scrape
from .web_search_tool import register_tools as register_web_search

# Web and PDF tools
from .wikipedia_tool import register_tools as register_wikipedia


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
    register_time(mcp)
    register_runtime_logs(mcp)
    register_wikipedia(mcp)
    register_arxiv(mcp)

    # Tools that need credentials (pass credentials if provided)
    # web_search supports multiple providers (Google, Brave) with auto-detection
    register_web_search(mcp, credentials=credentials)
    register_github(mcp, credentials=credentials)
    # email supports multiple providers (Gmail, Resend)
    register_email(mcp, credentials=credentials)
    # Gmail inbox management (read, trash, modify labels)
    register_gmail(mcp, credentials=credentials)
    register_hubspot(mcp, credentials=credentials)
    register_apollo(mcp, credentials=credentials)
    register_bigquery(mcp, credentials=credentials)
    register_calcom(mcp, credentials=credentials)
    register_calendar(mcp, credentials=credentials)
    register_discord(mcp, credentials=credentials)
    register_exa_search(mcp, credentials=credentials)
    register_news(mcp, credentials=credentials)
    register_razorpay(mcp, credentials=credentials)
    register_serpapi(mcp, credentials=credentials)
    register_slack(mcp, credentials=credentials)
    register_telegram(mcp, credentials=credentials)
    register_vision(mcp, credentials=credentials)
    register_google_docs(mcp, credentials=credentials)
    register_google_maps(mcp, credentials=credentials)
    register_account_info(mcp, credentials=credentials)

    # Register file system toolkits
    register_view_file(mcp)
    register_write_to_file(mcp)
    register_list_dir(mcp)
    register_replace_file_content(mcp)
    register_apply_diff(mcp)
    register_apply_patch(mcp)
    register_grep_search(mcp)
    register_execute_command(mcp)
    register_data_tools(mcp)
    register_csv(mcp)
    register_excel(mcp)

    # Security scanning tools (no credentials needed)
    register_ssl_tls_scanner(mcp)
    register_http_headers_scanner(mcp)
    register_dns_security_scanner(mcp)
    register_port_scanner(mcp)
    register_tech_stack_detector(mcp)
    register_subdomain_enumerator(mcp)
    register_risk_scorer(mcp)
    register_stripe(mcp, credentials=credentials)
    register_brevo(mcp, credentials=credentials)

    # Postgres tool
    register_postgres(mcp, credentials=credentials)

    # Return the list of all registered tool names
    return list(mcp._tool_manager._tools.keys())


__all__ = ["register_all_tools"]
