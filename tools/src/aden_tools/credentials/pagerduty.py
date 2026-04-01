"""
PagerDuty credentials.

Contains credentials for PagerDuty REST API v2.
Requires PAGERDUTY_API_KEY and optionally PAGERDUTY_FROM_EMAIL.
"""

from .base import CredentialSpec

PAGERDUTY_CREDENTIALS = {
    "pagerduty_api_key": CredentialSpec(
        env_var="PAGERDUTY_API_KEY",
        tools=[
            "pagerduty_list_incidents",
            "pagerduty_get_incident",
            "pagerduty_create_incident",
            "pagerduty_update_incident",
            "pagerduty_list_services",
            "pagerduty_list_oncalls",
            "pagerduty_add_incident_note",
            "pagerduty_list_escalation_policies",
        ],
        required=True,
        startup_required=False,
        help_url="https://support.pagerduty.com/docs/api-access-keys",
        description="PagerDuty REST API key (account-level or user-level)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up PagerDuty API access:
1. Go to PagerDuty > Integrations > API Access Keys
2. Create a new REST API key
3. Set environment variables:
   export PAGERDUTY_API_KEY=your-api-key
   export PAGERDUTY_FROM_EMAIL=your-pagerduty-email@example.com""",
        health_check_endpoint="",
        credential_id="pagerduty_api_key",
        credential_key="api_key",
    ),
    "pagerduty_from_email": CredentialSpec(
        env_var="PAGERDUTY_FROM_EMAIL",
        tools=[
            "pagerduty_create_incident",
            "pagerduty_update_incident",
            "pagerduty_add_incident_note",
        ],
        required=False,
        startup_required=False,
        help_url="https://support.pagerduty.com/docs/api-access-keys",
        description="PagerDuty user email (required for write operations)",
        direct_api_key_supported=True,
        api_key_instructions="""See PAGERDUTY_API_KEY instructions above.""",
        health_check_endpoint="",
        credential_id="pagerduty_from_email",
        credential_key="api_key",
    ),
}
