"""
WhatsApp Cloud API credentials.

Contains credentials for WhatsApp Business Cloud API integration.
Requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.
"""

from .base import CredentialSpec

_WHATSAPP_TOOLS = [
    "whatsapp_send_message",
    "whatsapp_send_template",
    "whatsapp_list_templates",
    "whatsapp_mark_as_read",
    "whatsapp_send_reaction",
    "whatsapp_send_image",
    "whatsapp_send_document",
]

WHATSAPP_CREDENTIALS = {
    "whatsapp": CredentialSpec(
        env_var="WHATSAPP_ACCESS_TOKEN",
        tools=_WHATSAPP_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://developers.facebook.com/apps/",
        description="WhatsApp Cloud API permanent access token",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a WhatsApp Cloud API access token:
1. Go to https://developers.facebook.com/apps/ and create a new app
2. Select "Business" as the app type
3. Add the "WhatsApp" product to your app
4. Go to WhatsApp > API Setup in the sidebar
5. Copy your permanent access token (or generate a temporary one)
6. Note your Phone Number ID from the same page
7. Set environment variables:
   export WHATSAPP_ACCESS_TOKEN=your-access-token
   export WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id""",
        health_check_endpoint="",
        health_check_method="GET",
        credential_id="whatsapp",
        credential_key="access_token",
        credential_group="whatsapp",
    ),
    "whatsapp_phone_number_id": CredentialSpec(
        env_var="WHATSAPP_PHONE_NUMBER_ID",
        tools=_WHATSAPP_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://developers.facebook.com/apps/",
        description="WhatsApp Business Phone Number ID from Meta dashboard",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""See WHATSAPP_ACCESS_TOKEN instructions above.""",
        health_check_endpoint="",
        credential_id="whatsapp_phone_number_id",
        credential_key="phone_number_id",
        credential_group="whatsapp",
    ),
}
