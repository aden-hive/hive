"""
Apify credentials.

Contains credentials for Apify web scraping and automation platform.
"""

from .base import CredentialSpec

APIFY_CREDENTIALS = {
    "apify": CredentialSpec(
        env_var="APIFY_API_TOKEN",
        tools=[
            "apify_run_actor",
            "apify_get_run",
            "apify_get_dataset_items",
            "apify_list_actors",
            "apify_list_runs",
            "apify_get_kv_store_record",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.apify.com/api/v2",
        description="Apify API token for running web scraping actors and retrieving datasets",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Apify API token:
1. Go to https://console.apify.com/account/integrations
2. Copy your personal API token
3. Set the environment variable:
   export APIFY_API_TOKEN=your-api-token""",
        health_check_endpoint="https://api.apify.com/v2/users/me",
        credential_id="apify",
        credential_key="api_key",
    ),
}
