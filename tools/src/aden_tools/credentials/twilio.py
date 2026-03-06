"""
Twilio credentials.

Contains credentials for Twilio SMS & WhatsApp messaging.
Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.
"""

from .base import CredentialSpec

TWILIO_CREDENTIALS = {
    "twilio_sid": CredentialSpec(
        env_var="TWILIO_ACCOUNT_SID",
        tools=[
            "twilio_send_sms",
            "twilio_send_whatsapp",
            "twilio_list_messages",
            "twilio_get_message",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.twilio.com/",
        description="Twilio Account SID (starts with AC)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Twilio API access:
1. Go to https://console.twilio.com/
2. Copy your Account SID and Auth Token from the dashboard
3. Set environment variables:
   export TWILIO_ACCOUNT_SID=your-account-sid
   export TWILIO_AUTH_TOKEN=your-auth-token""",
        health_check_endpoint="",
        credential_id="twilio_sid",
        credential_key="api_key",
    ),
    "twilio_token": CredentialSpec(
        env_var="TWILIO_AUTH_TOKEN",
        tools=[
            "twilio_send_sms",
            "twilio_send_whatsapp",
            "twilio_list_messages",
            "twilio_get_message",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.twilio.com/",
        description="Twilio Auth Token for API authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See TWILIO_ACCOUNT_SID instructions above.""",
        health_check_endpoint="",
        credential_id="twilio_token",
        credential_key="api_key",
    ),
}
