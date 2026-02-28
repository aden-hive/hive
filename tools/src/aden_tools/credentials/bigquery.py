"""
BigQuery tool credentials.

Contains credentials for Google BigQuery data warehouse access.
"""

from .base import CredentialSpec

BIGQUERY_CREDENTIALS = {
    "bigquery": CredentialSpec(
        env_var="GOOGLE_APPLICATION_CREDENTIALS",
        credential_group="google_cloud",
        tools=["run_bigquery_query", "describe_dataset"],
        required=False,  # Falls back to ADC if not set
        startup_required=False,
        help_url="https://cloud.google.com/bigquery/docs/authentication/service-account-file",
        description="Path to Google Cloud service account JSON file for BigQuery access",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To set up BigQuery authentication:

Option 1: Service Account (Recommended for production)
1. Go to Google Cloud Console > IAM & Admin > Service Accounts
2. Create a service account or select existing one
3. Grant roles: "BigQuery Data Viewer" and "BigQuery Job User"
4. Create a JSON key and download it
5. Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json

Option 2: Application Default Credentials (For local development)
1. Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install
2. Run: gcloud auth application-default login
3. Select your project when prompted""",
        # Credential store mapping
        credential_id="bigquery",
        credential_key="service_account_json_path",
    ),
    "bigquery_project": CredentialSpec(
        env_var="BIGQUERY_PROJECT_ID",
        tools=["run_bigquery_query", "describe_dataset"],
        required=False,
        startup_required=False,
        help_url="https://cloud.google.com/resource-manager/docs/creating-managing-projects",
        description="Default Google Cloud project ID for BigQuery queries",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="Set this to your Google Cloud project ID (e.g., 'my-project-123')",
        credential_id="bigquery_project",
        credential_key="project_id",
    ),
}
