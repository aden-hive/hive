"""
Email tool credentials.

Contains credentials for email providers like Resend, SendGrid, etc.
"""

from .base import CredentialSpec

EMAIL_CREDENTIALS = {
    "resend": CredentialSpec(
        env_var="RESEND_API_KEY",
        tools=["send_email", "send_budget_alert_email"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://resend.com/api-keys",
        description="API key for Resend email service",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get a Resend API key:
1. Go to https://resend.com and create an account (or sign in)
2. Navigate to API Keys in the dashboard
3. Click "Create API Key"
4. Give it a name (e.g., "Hive Agent") and choose permissions:
   - "Sending access" is sufficient for most use cases
   - "Full access" if you also need to manage domains
5. Copy the API key (starts with re_)
6. Store it securely - you won't be able to see it again!
7. Note: You'll also need to verify a domain to send emails from custom addresses""",
        # Health check configuration
        health_check_endpoint="https://api.resend.com/domains",
        # Credential store mapping
        credential_id="resend",
        credential_key="api_key",
    ),
}
