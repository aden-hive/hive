from aden_tools.credentials.base import CredentialSpec

DATADOG_CREDENTIALS = {
    "datadog": CredentialSpec(
        credential_id="datadog",
        env_var="DATADOG_API_KEY",
        credential_key="api_key",
        tools=["datadog_list_logs", "datadog_get_metrics", "datadog_get_monitor_status"],
        description="API key for Datadog observability",
        help_url="https://docs.datadoghq.com/account_management/api-app-keys/",
        health_check_endpoint="https://api.datadoghq.com/api/v1/validate",
        health_check_method="GET",
        direct_api_key_supported=True,
        api_key_instructions="""To create a Datadog API Key and Application Key:
1. Log in to your Datadog account: https://app.datadoghq.com/
2. Go to Organization Settings > API Keys: https://app.datadoghq.com/organization-settings/api-keys
3. Generate a new API Key.
4. Go to Organization Settings > Application Keys: https://app.datadoghq.com/organization-settings/application-keys
5. Generate a new Application Key.
6. Set the `DATADOG_API_KEY` environment variable with your API Key.
7. Set the `DATADOG_APP_KEY` environment variable with your Application Key.
8. (Optional) Set `DATADOG_SITE` for non-US regions (e.g., `datadoghq.eu`). Default is `datadoghq.com`."""
    )
}
