"""
Centralized credential management for Aden Tools.

Provides agent-aware validation, clear error messages, and testability.

Philosophy: Google Strictness + Apple UX
- Validate credentials before running an agent (fail-fast at the right boundary)
- Guided error messages with clear next steps

Usage:
    from aden_tools.credentials import CredentialStoreAdapter
    from framework.credentials import CredentialStore

    # With encrypted storage (production)
    store = CredentialStore.with_encrypted_storage()  # defaults to ~/.hive/credentials
    credentials = CredentialStoreAdapter(store)

    # With composite storage (encrypted primary + env fallback)
    credentials = CredentialStoreAdapter.default()

    # In agent runner (validate at agent load time)
    credentials.validate_for_tools(["web_search", "file_read"])

    # In tools
    api_key = credentials.get("brave_search")

    # In tests
    creds = CredentialStoreAdapter.for_testing({"brave_search": "test-key"})

    # Template resolution
    headers = credentials.resolve_headers({
        "Authorization": "Bearer {{github_oauth.access_token}}"
    })

Credential categories:
- search.py: Search tool credentials (brave_search, google_search, etc.)
- email.py: Email provider credentials (resend, google/gmail)
- apollo.py: Apollo.io API credentials
- brevo.py: Brevo (Sendinblue) transactional email/SMS credentials
- discord.py: Discord bot credentials
- github.py: GitHub API credentials
- google_analytics.py: Google Analytics 4 Data API credentials
- google_maps.py: Google Maps Platform credentials
- hubspot.py: HubSpot CRM credentials
- intercom.py: Intercom customer messaging credentials
- postgres.py: PostgreSQL database credentials
- slack.py: Slack workspace credentials
- stripe.py: Stripe payments API credentials
- calcom.py: Cal.com scheduling API credentials

Note: Tools that don't need credentials simply omit the 'credentials' parameter
from their register_tools() function. This convention is enforced by CI tests.

To add a new credential:
1. Find the appropriate category file (or create a new one)
2. Add the CredentialSpec to that file's dictionary
3. If new category, import and merge it in this __init__.py
"""

from .airtable import AIRTABLE_CREDENTIALS
from .apify import APIFY_CREDENTIALS
from .apollo import APOLLO_CREDENTIALS
from .asana import ASANA_CREDENTIALS
from .attio import ATTIO_CREDENTIALS
from .aws_s3 import AWS_S3_CREDENTIALS
from .azure_sql import AZURE_SQL_CREDENTIALS
from .base import CredentialError, CredentialSpec
from .bigquery import BIGQUERY_CREDENTIALS
from .brevo import BREVO_CREDENTIALS
from .browser import get_aden_auth_url, get_aden_setup_url, open_browser
from .calcom import CALCOM_CREDENTIALS
from .calendly import CALENDLY_CREDENTIALS
from .cloudflare import CLOUDFLARE_CREDENTIALS
from .cloudinary import CLOUDINARY_CREDENTIALS
from .confluence import CONFLUENCE_CREDENTIALS
from .databricks import DATABRICKS_CREDENTIALS
from .discord import DISCORD_CREDENTIALS
from .docker_hub import DOCKER_HUB_CREDENTIALS
from .email import EMAIL_CREDENTIALS
from .freshdesk import FRESHDESK_CREDENTIALS
from .gcp_vision import GCP_VISION_CREDENTIALS
from .github import GITHUB_CREDENTIALS
from .gitlab import GITLAB_CREDENTIALS
from .google_analytics import GOOGLE_ANALYTICS_CREDENTIALS
from .google_maps import GOOGLE_MAPS_CREDENTIALS
from .google_search_console import GOOGLE_SEARCH_CONSOLE_CREDENTIALS
from .greenhouse import GREENHOUSE_CREDENTIALS
from .health_check import (
    HealthCheckResult,
    check_credential_health,
)
from .hubspot import HUBSPOT_CREDENTIALS
from .huggingface import HUGGINGFACE_CREDENTIALS
from .intercom import INTERCOM_CREDENTIALS
from .jira import JIRA_CREDENTIALS
from .kafka import KAFKA_CREDENTIALS
from .langfuse import LANGFUSE_CREDENTIALS
from .linear import LINEAR_CREDENTIALS
from .lusha import LUSHA_CREDENTIALS
from .mattermost import MATTERMOST_CREDENTIALS
from .microsoft_graph import MICROSOFT_GRAPH_CREDENTIALS
from .mongodb import MONGODB_CREDENTIALS
from .n8n import N8N_CREDENTIALS
from .news import NEWS_CREDENTIALS
from .notion import NOTION_CREDENTIALS
from .obsidian import OBSIDIAN_CREDENTIALS
from .pagerduty import PAGERDUTY_CREDENTIALS
from .pinecone import PINECONE_CREDENTIALS
from .pipedrive import PIPEDRIVE_CREDENTIALS
from .plaid import PLAID_CREDENTIALS
from .postgres import POSTGRES_CREDENTIALS
from .powerbi import POWERBI_CREDENTIALS
from .prometheus import PROMETHEUS_CREDENTIALS
from .pushover import PUSHOVER_CREDENTIALS
from .quickbooks import QUICKBOOKS_CREDENTIALS
from .razorpay import RAZORPAY_CREDENTIALS
from .reddit import REDDIT_CREDENTIALS
from .redis import REDIS_CREDENTIALS
from .redshift import REDSHIFT_CREDENTIALS
from .salesforce import SALESFORCE_CREDENTIALS
from .sap import SAP_CREDENTIALS
from .search import SEARCH_CREDENTIALS
from .serpapi import SERPAPI_CREDENTIALS
from .shell_config import (
    add_env_var_to_shell_config,
    detect_shell,
    get_shell_config_path,
    get_shell_source_command,
)
from .shopify import SHOPIFY_CREDENTIALS
from .similarweb import SIMILARWEB_CREDENTIALS
from .slack import SLACK_CREDENTIALS
from .snowflake import SNOWFLAKE_CREDENTIALS
from .store_adapter import CredentialStoreAdapter
from .stripe import STRIPE_CREDENTIALS
from .supabase import SUPABASE_CREDENTIALS
from .telegram import TELEGRAM_CREDENTIALS
from .terraform import TERRAFORM_CREDENTIALS
from .tines import TINES_CREDENTIALS
from .trello import TRELLO_CREDENTIALS
from .twilio import TWILIO_CREDENTIALS
from .twitter import TWITTER_CREDENTIALS
from .vercel import VERCEL_CREDENTIALS
from .wandb import WANDB_CREDENTIALS
from .youtube import YOUTUBE_CREDENTIALS
from .zendesk import ZENDESK_CREDENTIALS
from .zoho_crm import ZOHO_CRM_CREDENTIALS
from .zoom import ZOOM_CREDENTIALS

# Merged registry of all credentials
CREDENTIAL_SPECS = {
    **AIRTABLE_CREDENTIALS,
    **NEWS_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **EMAIL_CREDENTIALS,
    **GCP_VISION_CREDENTIALS,
    **APIFY_CREDENTIALS,
    **APOLLO_CREDENTIALS,
    **ASANA_CREDENTIALS,
    **ATTIO_CREDENTIALS,
    **AWS_S3_CREDENTIALS,
    **AZURE_SQL_CREDENTIALS,
    **BIGQUERY_CREDENTIALS,
    **BREVO_CREDENTIALS,
    **CALCOM_CREDENTIALS,
    **CALENDLY_CREDENTIALS,
    **CLOUDFLARE_CREDENTIALS,
    **CLOUDINARY_CREDENTIALS,
    **CONFLUENCE_CREDENTIALS,
    **DATABRICKS_CREDENTIALS,
    **DISCORD_CREDENTIALS,
    **DOCKER_HUB_CREDENTIALS,
    **EMAIL_CREDENTIALS,
    **GCP_VISION_CREDENTIALS,
    **GITHUB_CREDENTIALS,
    **GREENHOUSE_CREDENTIALS,
    **GITLAB_CREDENTIALS,
    **GOOGLE_ANALYTICS_CREDENTIALS,
    **GOOGLE_MAPS_CREDENTIALS,
    **GOOGLE_SEARCH_CONSOLE_CREDENTIALS,
    **HUBSPOT_CREDENTIALS,
    **HUGGINGFACE_CREDENTIALS,
    **INTERCOM_CREDENTIALS,
    **JIRA_CREDENTIALS,
    **KAFKA_CREDENTIALS,
    **LANGFUSE_CREDENTIALS,
    **LINEAR_CREDENTIALS,
    **LUSHA_CREDENTIALS,
    **MATTERMOST_CREDENTIALS,
    **MICROSOFT_GRAPH_CREDENTIALS,
    **MONGODB_CREDENTIALS,
    **N8N_CREDENTIALS,
    **NEWS_CREDENTIALS,
    **NOTION_CREDENTIALS,
    **OBSIDIAN_CREDENTIALS,
    **PAGERDUTY_CREDENTIALS,
    **PINECONE_CREDENTIALS,
    **PIPEDRIVE_CREDENTIALS,
    **PLAID_CREDENTIALS,
    **POSTGRES_CREDENTIALS,
    **POWERBI_CREDENTIALS,
    **PROMETHEUS_CREDENTIALS,
    **PUSHOVER_CREDENTIALS,
    **QUICKBOOKS_CREDENTIALS,
    **RAZORPAY_CREDENTIALS,
    **REDDIT_CREDENTIALS,
    **REDIS_CREDENTIALS,
    **REDSHIFT_CREDENTIALS,
    **SALESFORCE_CREDENTIALS,
    **SAP_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **SERPAPI_CREDENTIALS,
    **SIMILARWEB_CREDENTIALS,
    **SHOPIFY_CREDENTIALS,
    **SLACK_CREDENTIALS,
    **SNOWFLAKE_CREDENTIALS,
    **STRIPE_CREDENTIALS,
    **SUPABASE_CREDENTIALS,
    **TELEGRAM_CREDENTIALS,
    **TERRAFORM_CREDENTIALS,
    **TINES_CREDENTIALS,
    **TRELLO_CREDENTIALS,
    **TWILIO_CREDENTIALS,
    **TWITTER_CREDENTIALS,
    **VERCEL_CREDENTIALS,
    **YOUTUBE_CREDENTIALS,
    **WANDB_CREDENTIALS,
    **ZENDESK_CREDENTIALS,
    **ZOHO_CRM_CREDENTIALS,
    **ZOOM_CREDENTIALS,
    **FRESHDESK_CREDENTIALS,
}

__all__ = [
    # Core classes
    "CredentialSpec",
    "CredentialStoreAdapter",
    "CredentialError",
    # Health check utilities
    "HealthCheckResult",
    "check_credential_health",
    # Browser utilities for OAuth2 flows
    "open_browser",
    "get_aden_auth_url",
    "get_aden_setup_url",
    # Shell config utilities
    "detect_shell",
    "get_shell_config_path",
    "get_shell_source_command",
    "add_env_var_to_shell_config",
    # Merged registry
    "CREDENTIAL_SPECS",
    # Category registries
    "AIRTABLE_CREDENTIALS",
    "APIFY_CREDENTIALS",
    "APOLLO_CREDENTIALS",
    "ASANA_CREDENTIALS",
    "ATTIO_CREDENTIALS",
    "AWS_S3_CREDENTIALS",
    "AZURE_SQL_CREDENTIALS",
    "BIGQUERY_CREDENTIALS",
    "BREVO_CREDENTIALS",
    "CALCOM_CREDENTIALS",
    "CALENDLY_CREDENTIALS",
    "CLOUDFLARE_CREDENTIALS",
    "CLOUDINARY_CREDENTIALS",
    "CONFLUENCE_CREDENTIALS",
    "DATABRICKS_CREDENTIALS",
    "DISCORD_CREDENTIALS",
    "DOCKER_HUB_CREDENTIALS",
    "EMAIL_CREDENTIALS",
    "GCP_VISION_CREDENTIALS",
    "GITHUB_CREDENTIALS",
    "GREENHOUSE_CREDENTIALS",
    "GITLAB_CREDENTIALS",
    "GOOGLE_ANALYTICS_CREDENTIALS",
    "GOOGLE_MAPS_CREDENTIALS",
    "GOOGLE_SEARCH_CONSOLE_CREDENTIALS",
    "HUBSPOT_CREDENTIALS",
    "HUGGINGFACE_CREDENTIALS",
    "INTERCOM_CREDENTIALS",
    "JIRA_CREDENTIALS",
    "KAFKA_CREDENTIALS",
    "LANGFUSE_CREDENTIALS",
    "LINEAR_CREDENTIALS",
    "LUSHA_CREDENTIALS",
    "MATTERMOST_CREDENTIALS",
    "MICROSOFT_GRAPH_CREDENTIALS",
    "MONGODB_CREDENTIALS",
    "N8N_CREDENTIALS",
    "NEWS_CREDENTIALS",
    "NOTION_CREDENTIALS",
    "OBSIDIAN_CREDENTIALS",
    "PAGERDUTY_CREDENTIALS",
    "PINECONE_CREDENTIALS",
    "PIPEDRIVE_CREDENTIALS",
    "PLAID_CREDENTIALS",
    "POSTGRES_CREDENTIALS",
    "POWERBI_CREDENTIALS",
    "PROMETHEUS_CREDENTIALS",
    "PUSHOVER_CREDENTIALS",
    "QUICKBOOKS_CREDENTIALS",
    "RAZORPAY_CREDENTIALS",
    "REDDIT_CREDENTIALS",
    "REDIS_CREDENTIALS",
    "REDSHIFT_CREDENTIALS",
    "SALESFORCE_CREDENTIALS",
    "SAP_CREDENTIALS",
    "SEARCH_CREDENTIALS",
    "SERPAPI_CREDENTIALS",
    "SIMILARWEB_CREDENTIALS",
    "SHOPIFY_CREDENTIALS",
    "SLACK_CREDENTIALS",
    "SNOWFLAKE_CREDENTIALS",
    "STRIPE_CREDENTIALS",
    "SUPABASE_CREDENTIALS",
    "TELEGRAM_CREDENTIALS",
    "TERRAFORM_CREDENTIALS",
    "TINES_CREDENTIALS",
    "TRELLO_CREDENTIALS",
    "TWILIO_CREDENTIALS",
    "TWITTER_CREDENTIALS",
    "VERCEL_CREDENTIALS",
    "WANDB_CREDENTIALS",
    "YOUTUBE_CREDENTIALS",
    "ZENDESK_CREDENTIALS",
    "ZOHO_CRM_CREDENTIALS",
    "ZOOM_CREDENTIALS",
    "FRESHDESK_CREDENTIALS",
]
