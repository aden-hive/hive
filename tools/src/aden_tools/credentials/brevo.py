"""
Brevo tool credentials.
Contains credentials for Brevo email and SMS integration.
"""
from .base import CredentialSpec

BREVO_CREDENTIALS = {
    "brevo": CredentialSpec(
        env_var="BREVO_API_KEY",
        tools=[
            "brevo_send_email",
            "brevo_send_sms",
            "brevo_create_contact",
            "brevo_get_contact",
            "brevo_update_contact",
            "brevo_get_email_stats",
        ],
        required=True,
        startup_required=False,
        help_url="https://app.brevo.com/settings/keys/api",
        description="Brevo API key for transactional email, SMS, and contact management",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Brevo API key:
1. Sign up or log in at https://www.brevo.com
2. Go to Settings → API Keys
3. Click 'Generate a new API key'
4. Give it a name (e.g., 'Hive Agent')
5. Copy the API key and set it as BREVO_API_KEY""",
        health_check_endpoint="https://api.brevo.com/v3/account",
        health_check_method="GET",
        credential_id="brevo",
        credential_key="api_key",
    ),
}