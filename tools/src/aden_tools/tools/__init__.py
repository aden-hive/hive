"""
Aden Tools - Tool implementations for FastMCP.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialStoreAdapter

    mcp = FastMCP("my-server")
    credentials = CredentialStoreAdapter.default()
    register_all_tools(mcp, credentials=credentials)

    # To also load unverified (community/new) integrations:
    register_all_tools(mcp, credentials=credentials, include_unverified=True)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# ---------------------------------------------------------------------------
# Verified tools (stable, on main)
# ---------------------------------------------------------------------------
from .account_info_tool import register_tools as register_account_info

# ---------------------------------------------------------------------------
# Unverified tools (new integrations, pending review)
# ---------------------------------------------------------------------------
from .airtable_tool import register_tools as register_airtable
from .apify_tool import register_tools as register_apify
from .apollo_tool import register_tools as register_apollo
from .arxiv_tool import register_tools as register_arxiv
from .asana_tool import register_tools as register_asana
from .attio_tool import register_tools as register_attio
from .aws_s3_tool import register_tools as register_aws_s3
from .azure_sql_tool import register_tools as register_azure_sql
from .bigquery_tool import register_tools as register_bigquery
from .brevo_tool import register_tools as register_brevo
from .calcom_tool import register_tools as register_calcom
from .calendar_tool import register_tools as register_calendar
from .calendly_tool import register_tools as register_calendly
from .cloudinary_tool import register_tools as register_cloudinary
from .confluence_tool import register_tools as register_confluence
from .csv_tool import register_tools as register_csv
from .databricks_tool import register_tools as register_databricks
from .discord_tool import register_tools as register_discord
from .dns_security_scanner import register_tools as register_dns_security_scanner
from .docker_hub_tool import register_tools as register_docker_hub
from .duckduckgo_tool import register_tools as register_duckduckgo
from .email_tool import register_tools as register_email
from .exa_search_tool import register_tools as register_exa_search
from .example_tool import register_tools as register_example
from .excel_tool import register_tools as register_excel

# File system toolkits
from .file_system_toolkits.apply_diff import register_tools as register_apply_diff
from .file_system_toolkits.apply_patch import register_tools as register_apply_patch
from .file_system_toolkits.data_tools import register_tools as register_data_tools
from .file_system_toolkits.execute_command_tool import (
    register_tools as register_execute_command,
)
from .file_system_toolkits.grep_search import register_tools as register_grep_search
from .file_system_toolkits.hashline_edit import register_tools as register_hashline_edit
from .file_system_toolkits.list_dir import register_tools as register_list_dir
from .file_system_toolkits.replace_file_content import (
    register_tools as register_replace_file_content,
)
from .github_tool import register_tools as register_github
from .gitlab_tool import register_tools as register_gitlab
from .gmail_tool import register_tools as register_gmail
from .google_analytics_tool import register_tools as register_google_analytics
from .google_docs_tool import register_tools as register_google_docs
from .google_maps_tool import register_tools as register_google_maps
from .google_search_console_tool import register_tools as register_google_search_console
from .google_sheets_tool import register_tools as register_google_sheets
from .greenhouse_tool import register_tools as register_greenhouse
from .http_headers_scanner import register_tools as register_http_headers_scanner
from .hubspot_tool import register_tools as register_hubspot
from .huggingface_tool import register_tools as register_huggingface
from .intercom_tool import register_tools as register_intercom
from .jira_tool import register_tools as register_jira
from .kafka_tool import register_tools as register_kafka
from .langfuse_tool import register_tools as register_langfuse
from .linear_tool import register_tools as register_linear
from .lusha_tool import register_tools as register_lusha
from .mattermost_tool import register_tools as register_mattermost
from .microsoft_graph_tool import register_tools as register_microsoft_graph
from .mongodb_tool import register_tools as register_mongodb
from .n8n_tool import register_tools as register_n8n
from .news_tool import register_tools as register_news
from .notion_tool import register_tools as register_notion
from .obsidian_tool import register_tools as register_obsidian
from .pagerduty_tool import register_tools as register_pagerduty
from .pdf_read_tool import register_tools as register_pdf_read
from .pinecone_tool import register_tools as register_pinecone
from .pipedrive_tool import register_tools as register_pipedrive
from .plaid_tool import register_tools as register_plaid
from .port_scanner import register_tools as register_port_scanner
from .postgres_tool import register_tools as register_postgres
from .powerbi_tool import register_tools as register_powerbi
from .pushover_tool import register_tools as register_pushover
from .quickbooks_tool import register_tools as register_quickbooks
from .razorpay_tool import register_tools as register_razorpay
from .reddit_tool import register_tools as register_reddit
from .redis_tool import register_tools as register_redis
from .redshift_tool import register_tools as register_redshift
from .risk_scorer import register_tools as register_risk_scorer
from .runtime_logs_tool import register_tools as register_runtime_logs
from .salesforce_tool import register_tools as register_salesforce
from .sap_tool import register_tools as register_sap
from .serpapi_tool import register_tools as register_serpapi
from .shopify_tool import register_tools as register_shopify
from .slack_tool import register_tools as register_slack
from .snowflake_tool import register_tools as register_snowflake
from .ssl_tls_scanner import register_tools as register_ssl_tls_scanner
from .stripe_tool import register_tools as register_stripe
from .subdomain_enumerator import register_tools as register_subdomain_enumerator
from .supabase_tool import register_tools as register_supabase
from .tech_stack_detector import register_tools as register_tech_stack_detector
from .telegram_tool import register_tools as register_telegram
from .terraform_tool import register_tools as register_terraform
from .time_tool import register_tools as register_time
from .tines_tool import register_tools as register_tines
from .trello_tool import register_tools as register_trello
from .twilio_tool import register_tools as register_twilio
from .twitter_tool import register_tools as register_twitter
from .vercel_tool import register_tools as register_vercel
from .vision_tool import register_tools as register_vision
from .web_scrape_tool import register_tools as register_web_scrape
from .web_search_tool import register_tools as register_web_search
from .wikipedia_tool import register_tools as register_wikipedia
from .yahoo_finance_tool import register_tools as register_yahoo_finance
from .youtube_tool import register_tools as register_youtube
from .youtube_transcript_tool import register_tools as register_youtube_transcript
from .zendesk_tool import register_tools as register_zendesk
from .zoho_crm_tool import register_tools as register_zoho_crm
from .zoom_tool import register_tools as register_zoom


def _register_verified(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register verified (stable) tools."""
    # --- No credentials ---
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
    register_intercom(mcp, credentials=credentials)
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
    register_google_analytics(mcp, credentials=credentials)
    register_google_docs(mcp, credentials=credentials)
    register_google_maps(mcp, credentials=credentials)
    register_google_sheets(mcp, credentials=credentials)
    register_account_info(mcp, credentials=credentials)

    # --- File system toolkits ---
    register_list_dir(mcp)
    register_replace_file_content(mcp)
    register_apply_diff(mcp)
    register_apply_patch(mcp)
    register_grep_search(mcp)
    # hashline_edit: anchor-based editing, pairs with read_file/grep_search hashline mode
    register_hashline_edit(mcp)
    register_execute_command(mcp)
    register_data_tools(mcp)
    register_csv(mcp)
    register_excel(mcp)

    # --- Security scanning (no credentials) ---
    register_ssl_tls_scanner(mcp)
    register_http_headers_scanner(mcp)
    register_dns_security_scanner(mcp)
    register_port_scanner(mcp)
    register_tech_stack_detector(mcp)
    register_subdomain_enumerator(mcp)
    register_risk_scorer(mcp)

    # --- Credentials required ---
    register_web_search(mcp, credentials=credentials)
    register_github(mcp, credentials=credentials)
    register_email(mcp, credentials=credentials)
    register_gmail(mcp, credentials=credentials)
    register_hubspot(mcp, credentials=credentials)
    register_calendar(mcp, credentials=credentials)
    register_discord(mcp, credentials=credentials)
    register_exa_search(mcp, credentials=credentials)
    register_news(mcp, credentials=credentials)
    register_slack(mcp, credentials=credentials)
    register_telegram(mcp, credentials=credentials)
    register_google_docs(mcp, credentials=credentials)
    register_google_maps(mcp, credentials=credentials)
    register_notion(mcp, credentials=credentials)
    register_account_info(mcp, credentials=credentials)


def _register_unverified(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register unverified (new/community) tools."""
    # --- No credentials ---
    register_duckduckgo(mcp)
    register_yahoo_finance(mcp)
    register_youtube_transcript(mcp)

    # --- Credentials required ---
    register_airtable(mcp, credentials=credentials)
    register_apify(mcp, credentials=credentials)
    register_asana(mcp, credentials=credentials)
    register_attio(mcp, credentials=credentials)
    register_aws_s3(mcp, credentials=credentials)
    register_azure_sql(mcp, credentials=credentials)
    register_intercom(mcp, credentials=credentials)
    register_apollo(mcp, credentials=credentials)
    register_brevo(mcp, credentials=credentials)
    register_bigquery(mcp, credentials=credentials)
    register_calcom(mcp, credentials=credentials)
    register_razorpay(mcp, credentials=credentials)
    register_serpapi(mcp, credentials=credentials)
    register_vision(mcp, credentials=credentials)
    register_stripe(mcp, credentials=credentials)
    register_postgres(mcp, credentials=credentials)
    register_calendly(mcp, credentials=credentials)
    register_cloudinary(mcp, credentials=credentials)
    register_confluence(mcp, credentials=credentials)
    register_databricks(mcp, credentials=credentials)
    register_docker_hub(mcp, credentials=credentials)
    register_gitlab(mcp, credentials=credentials)
    register_google_analytics(mcp, credentials=credentials)
    register_google_search_console(mcp, credentials=credentials)
    register_google_sheets(mcp, credentials=credentials)
    register_greenhouse(mcp, credentials=credentials)
    register_huggingface(mcp, credentials=credentials)
    register_jira(mcp, credentials=credentials)
    register_kafka(mcp, credentials=credentials)
    register_langfuse(mcp, credentials=credentials)
    register_linear(mcp, credentials=credentials)
    register_lusha(mcp, credentials=credentials)
    register_mattermost(mcp, credentials=credentials)
    register_microsoft_graph(mcp, credentials=credentials)
    register_mongodb(mcp, credentials=credentials)
    register_n8n(mcp, credentials=credentials)
    register_obsidian(mcp, credentials=credentials)
    register_pagerduty(mcp, credentials=credentials)
    register_pinecone(mcp, credentials=credentials)
    register_pipedrive(mcp, credentials=credentials)
    register_plaid(mcp, credentials=credentials)
    register_powerbi(mcp, credentials=credentials)
    register_pushover(mcp, credentials=credentials)
    register_quickbooks(mcp, credentials=credentials)
    register_reddit(mcp, credentials=credentials)
    register_redis(mcp, credentials=credentials)
    register_redshift(mcp, credentials=credentials)
    register_salesforce(mcp, credentials=credentials)
    register_sap(mcp, credentials=credentials)
    register_shopify(mcp, credentials=credentials)
    register_snowflake(mcp, credentials=credentials)
    register_supabase(mcp, credentials=credentials)
    register_terraform(mcp, credentials=credentials)
    register_tines(mcp, credentials=credentials)
    register_trello(mcp, credentials=credentials)
    register_twilio(mcp, credentials=credentials)
    register_twitter(mcp, credentials=credentials)
    register_vercel(mcp, credentials=credentials)
    register_youtube(mcp, credentials=credentials)
    register_zendesk(mcp, credentials=credentials)
    register_zoho_crm(mcp, credentials=credentials)
    register_zoom(mcp, credentials=credentials)


def register_all_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
    include_unverified: bool = False,
) -> list[str]:
    """
    Register all tools with a FastMCP server.

    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter instance.
                     If not provided, tools fall back to direct os.getenv() calls.
        include_unverified: If True, also register unverified/community tools.
                           Defaults to False for production safety.

    Returns:
        List of registered tool names
    """
    _register_verified(mcp, credentials=credentials)

    if include_unverified:
        _register_unverified(mcp, credentials=credentials)

    return list(mcp._tool_manager._tools.keys())


__all__ = ["register_all_tools"]
