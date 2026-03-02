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
}
