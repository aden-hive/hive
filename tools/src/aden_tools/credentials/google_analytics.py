"""
Google Analytics credentials.

Contains credentials for Google Analytics 4 Data API integration.
"""

from .base import CredentialSpec

GOOGLE_ANALYTICS_CREDENTIALS = {
    "google_analytics": CredentialSpec(
        env_var="GOOGLE_APPLICATION_CREDENTIALS",
        credential_group="google_cloud",
        tools=[
            "ga_run_report",
            "ga_get_realtime",
            "ga_get_top_pages",
            "ga_get_traffic_sources",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart-client-libraries",
        description="Path to Google Cloud service account JSON key with Analytics read access",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To set up Google Analytics credentials:
1. Go to Google Cloud Console > IAM & Admin > Service Accounts
2. Create a service account (e.g., "hive-analytics-reader")
3. Download the JSON key file
4. In Google Analytics, go to Admin > Property > Property Access Management
5. Add the service account email with "Viewer" role
6. Set the env var to the path of the JSON key file:
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json""",
        # Health check - GA4 Data API doesn't have a simple health endpoint
        health_check_endpoint="",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_analytics",
        credential_key="service_account_key_path",
    ),
}
