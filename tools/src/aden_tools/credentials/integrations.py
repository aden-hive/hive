"""
Integration credentials for common third-party services.
"""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
    "twilio_account_sid": CredentialSpec(
        env_var="TWILIO_ACCOUNT_SID",
        tools=["send_sms", "send_whatsapp", "fetch_history", "validate_number"],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://www.twilio.com/console",
        description="Twilio Account SID",
    ),
    "twilio_auth_token": CredentialSpec(
        env_var="TWILIO_AUTH_TOKEN",
        tools=["send_sms", "send_whatsapp", "fetch_history", "validate_number"],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://www.twilio.com/console",
        description="Twilio Auth Token",
    ),
    "twilio_from_number": CredentialSpec(
        env_var="TWILIO_FROM_NUMBER",
        tools=["send_sms", "send_whatsapp"],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://www.twilio.com/console/phone-numbers/incoming",
        description="Default 'from' phone number for Twilio messages",
    ),
}
