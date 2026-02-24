"""
Brevo tool credentials.

Contains credentials for Brevo (formerly Sendinblue) transactional email,
SMS, and contact management integration.
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
        ],
        required=True,
        startup_required=False,
        help_url="https://app.brevo.com/settings/keys/api",
        description="Brevo API key for transactional email, SMS, and contact management",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Brevo API key:
1. Go to https://app.brevo.com and create an account (or sign in)
2. Navigate to Settings > API Keys (or visit https://app.brevo.com/settings/keys/api)
3. Click "Generate a new API key"
4. Give it a name (e.g., "Hive Agent")
5. Copy the API key (starts with xkeysib-)
6. Store it securely - you won't be able to see it again!
7. Note: For sending emails, you'll need a verified sender domain or email""",
        # Health check configuration
        health_check_endpoint="https://api.brevo.com/v3/account",
        health_check_method="GET",
        # Credential store mapping
        credential_id="brevo",
        credential_key="api_key",
    ),
}
