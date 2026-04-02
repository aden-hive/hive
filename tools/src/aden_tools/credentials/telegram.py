"""
Telegram tool credentials.

Contains credentials for Telegram Bot API integration.
"""

from .base import CredentialSpec

TELEGRAM_CREDENTIALS = {
    "telegram": CredentialSpec(
        env_var="TELEGRAM_BOT_TOKEN",
        tools=[
            "telegram_send_message",
            "telegram_send_document",
            "telegram_edit_message",
            "telegram_delete_message",
            "telegram_forward_message",
            "telegram_send_photo",
            "telegram_send_chat_action",
            "telegram_get_chat",
            "telegram_pin_message",
            "telegram_unpin_message",
            "telegram_get_chat_member_count",
            "telegram_send_video",
            "telegram_set_chat_description",
            "telegram_get_chat_id",
        ],
        required=True,
        startup_required=False,
        help_url="https://core.telegram.org/bots#botfather",
        description="Telegram Bot Token from @BotFather",
        # Auth method support
        aden_supported=False,
        aden_provider_name=None,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Telegram Bot Token:
1. Open Telegram and search for @BotFather
2. Send /newbot command
3. Follow the prompts to name your bot
4. Copy the HTTP API token provided
5. Set as TELEGRAM_BOT_TOKEN environment variable""",
        # Health check configuration
        health_check_endpoint="https://api.telegram.org/bot{token}/getMe",
        health_check_method="GET",
        # Credential store mapping
        credential_id="telegram",
        credential_key="bot_token",
    ),
    "telegram_chat_id": CredentialSpec(
        env_var="TELEGRAM_CHAT_ID",
        tools=[
            "telegram_send_message",
            "telegram_send_document",
            "telegram_send_photo",
            "telegram_send_video",
            "telegram_edit_message",
            "telegram_delete_message",
            "telegram_forward_message",
            "telegram_send_chat_action",
            "telegram_pin_message",
            "telegram_unpin_message",
            "telegram_get_chat_member_count",
            "telegram_set_chat_description",
        ],
        required=False,
        startup_required=False,
        help_url="https://api.telegram.org/bot<TOKEN>/getUpdates",
        description="Telegram Chat ID (numeric for users/groups)",
        # Auth method support
        aden_supported=False,
        aden_provider_name=None,
        direct_api_key_supported=False,
        api_key_instructions="""To get your Telegram Chat ID:
OPTIONAL: Can be auto-discovered via telegram_get_chat_id tool if bot has recent messages.
MANUAL:
1. Start a chat with your bot on Telegram
2. Send any message to the bot
3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates
4. Look for "chat":{"id":123456789} in the response
5. The number in "id" is your chat ID""",
        # Credential store mapping
        credential_id="telegram_chat_id",
        credential_key="chat_id",
    ),
}
