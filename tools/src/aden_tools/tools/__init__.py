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
from .apify_tool import register_tools as register_apify
from .aws_s3_tool import register_tools as register_aws_s3
from .asana_tool import register_tools as register_asana
from .apollo_tool import register_tools as register_apollo
from .arxiv_tool import register_tools as register_arxiv
from .attio_tool import register_tools as register_attio
from .bigquery_tool import register_tools as register_bigquery
from .brevo_tool import register_tools as register_brevo
from .calcom_tool import register_tools as register_calcom
from .calendly_tool import register_tools as register_calendly
from .confluence_tool import register_tools as register_confluence
from .calendar_tool import register_tools as register_calendar
from .csv_tool import register_tools as register_csv
from .databricks_tool import register_tools as register_databricks
from .discord_tool import register_tools as register_discord
from .docker_hub_tool import register_tools as register_docker_hub
from .duckduckgo_tool import register_tools as register_duckduckgo
from .pipedrive_tool import register_tools as register_pipedrive

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
from .google_analytics_tool import register_tools as register_google_analytics
from .google_docs_tool import register_tools as register_google_docs
from .google_maps_tool import register_tools as register_google_maps
from .google_search_console_tool import register_tools as register_google_search_console
from .http_headers_scanner import register_tools as register_http_headers_scanner
from .huggingface_tool import register_tools as register_huggingface
from .hubspot_tool import register_tools as register_hubspot
from .linear_tool import register_tools as register_linear
from .intercom_tool import register_tools as register_intercom
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
from .microsoft_graph_tool import register_tools as register_microsoft_graph
from .pushover_tool import register_tools as register_pushover
from .redis_tool import register_tools as register_redis
from .supabase_tool import register_tools as register_supabase
from .vercel_tool import register_tools as register_vercel
from .web_search_tool import register_tools as register_web_search
from .yahoo_finance_tool import register_tools as register_yahoo_finance
from .pinecone_tool import register_tools as register_pinecone
from .plaid_tool import register_tools as register_plaid
from .trello_tool import register_tools as register_trello
from .airtable_tool import register_tools as register_airtable
from .cloudinary_tool import register_tools as register_cloudinary
from .gitlab_tool import register_tools as register_gitlab
from .google_sheets_tool import register_tools as register_google_sheets
from .greenhouse_tool import register_tools as register_greenhouse
from .jira_tool import register_tools as register_jira
from .mongodb_tool import register_tools as register_mongodb
from .notion_tool import register_tools as register_notion
from .pagerduty_tool import register_tools as register_pagerduty
from .quickbooks_tool import register_tools as register_quickbooks
from .reddit_tool import register_tools as register_reddit
from .tines_tool import register_tools as register_tines
from .twilio_tool import register_tools as register_twilio
from .twitter_tool import register_tools as register_twitter
from .youtube_transcript_tool import register_tools as register_youtube_transcript
from .zendesk_tool import register_tools as register_zendesk
from .zoho_crm_tool import register_tools as register_zoho_crm
from .terraform_tool import register_tools as register_terraform
from .lusha_tool import register_tools as register_lusha
from .powerbi_tool import register_tools as register_powerbi
from .snowflake_tool import register_tools as register_snowflake
from .azure_sql_tool import register_tools as register_azure_sql
from .kafka_tool import register_tools as register_kafka
from .redshift_tool import register_tools as register_redshift
from .sap_tool import register_tools as register_sap
from .salesforce_tool import register_tools as register_salesforce
from .shopify_tool import register_tools as register_shopify
from .zoom_tool import register_tools as register_zoom
from .n8n_tool import register_tools as register_n8n
from .langfuse_tool import register_tools as register_langfuse
from .obsidian_tool import register_tools as register_obsidian

# Web and PDF tools
from .wikipedia_tool import register_tools as register_wikipedia
from .youtube_tool import register_tools as register_youtube


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
    register_yahoo_finance(mcp)
    register_duckduckgo(mcp)

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

    # Databricks (SQL, Jobs, Clusters, Workspace)
    register_databricks(mcp, credentials=credentials)

    # Microsoft Graph (Outlook, Teams, OneDrive)
    register_microsoft_graph(mcp, credentials=credentials)

    # Pushover push notifications
    register_pushover(mcp, credentials=credentials)

    # Redis in-memory data store
    register_redis(mcp, credentials=credentials)

    # Supabase (DB, Auth, Edge Functions)
    register_supabase(mcp, credentials=credentials)

    # Vercel deployment & hosting
    register_vercel(mcp, credentials=credentials)

    # YouTube Data API
    register_youtube(mcp, credentials=credentials)

    # Docker Hub repository & image management
    register_docker_hub(mcp, credentials=credentials)

    # Pipedrive CRM (Deals, Contacts, Organizations, Activities)
    register_pipedrive(mcp, credentials=credentials)

    # Attio CRM (Records, Lists, Notes, Tasks)
    register_attio(mcp, credentials=credentials)

    # Apify web scraping & automation
    register_apify(mcp, credentials=credentials)

    # Zoho CRM (Leads, Contacts, Deals, Accounts)
    register_zoho_crm(mcp, credentials=credentials)

    # Google Search Console (Analytics, Sitemaps, URL Inspection)
    register_google_search_console(mcp, credentials=credentials)

    # Asana task & project management
    register_asana(mcp, credentials=credentials)

    # Linear issue tracking
    register_linear(mcp, credentials=credentials)

    # Pinecone vector database
    register_pinecone(mcp, credentials=credentials)

    # Plaid banking & financial data
    register_plaid(mcp, credentials=credentials)

    # HuggingFace Hub (models, datasets, spaces)
    register_huggingface(mcp, credentials=credentials)

    # Trello board & card management
    register_trello(mcp, credentials=credentials)

    # Confluence wiki & knowledge management
    register_confluence(mcp, credentials=credentials)

    # Cloudinary image/video management
    register_cloudinary(mcp, credentials=credentials)

    # Reddit community content monitoring
    register_reddit(mcp, credentials=credentials)

    # Greenhouse ATS & recruiting
    register_greenhouse(mcp, credentials=credentials)

    # YouTube Transcript (no credentials needed)
    register_youtube_transcript(mcp)

    # Notion pages, databases, and search
    register_notion(mcp, credentials=credentials)

    # Jira issue tracking and project management
    register_jira(mcp, credentials=credentials)

    # GitLab projects, issues, and merge requests
    register_gitlab(mcp, credentials=credentials)

    # Google Sheets spreadsheet data
    register_google_sheets(mcp, credentials=credentials)

    # Twilio SMS & WhatsApp messaging
    register_twilio(mcp, credentials=credentials)

    # Zendesk ticket management
    register_zendesk(mcp, credentials=credentials)

    # MongoDB Atlas Data API
    register_mongodb(mcp, credentials=credentials)

    # Airtable records and bases
    register_airtable(mcp, credentials=credentials)

    # PagerDuty incident management
    register_pagerduty(mcp, credentials=credentials)

    # Calendly scheduling events
    register_calendly(mcp, credentials=credentials)

    # AWS S3 object storage
    register_aws_s3(mcp, credentials=credentials)

    # QuickBooks Online accounting
    register_quickbooks(mcp, credentials=credentials)

    # Twitter/X social media
    register_twitter(mcp, credentials=credentials)

    # Tines security automation
    register_tines(mcp, credentials=credentials)

    # Terraform Cloud workspaces and runs
    register_terraform(mcp, credentials=credentials)

    # Lusha B2B contact and company data
    register_lusha(mcp, credentials=credentials)

    # Power BI reports and datasets
    register_powerbi(mcp, credentials=credentials)

    # Snowflake SQL queries
    register_snowflake(mcp, credentials=credentials)

    # Azure SQL Database management
    register_azure_sql(mcp, credentials=credentials)

    # Apache Kafka (Confluent REST Proxy)
    register_kafka(mcp, credentials=credentials)

    # Amazon Redshift Data API
    register_redshift(mcp, credentials=credentials)

    # SAP S/4HANA Cloud (read-only procurement)
    register_sap(mcp, credentials=credentials)

    # Salesforce CRM (Leads, Contacts, Opportunities, SOQL)
    register_salesforce(mcp, credentials=credentials)

    # Shopify Admin (Orders, Products, Customers)
    register_shopify(mcp, credentials=credentials)

    # Zoom meeting management
    register_zoom(mcp, credentials=credentials)

    # n8n workflow automation
    register_n8n(mcp, credentials=credentials)

    # Langfuse LLM observability
    register_langfuse(mcp, credentials=credentials)

    # Obsidian knowledge management
    register_obsidian(mcp, credentials=credentials)

    # Return the list of all registered tool names
    return list(mcp._tool_manager._tools.keys())


__all__ = ["register_all_tools"]
