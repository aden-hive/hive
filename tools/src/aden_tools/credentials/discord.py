"""
Discord tool credentials.

Contains credentials for Discord bot integration.
"""

from .base import CredentialSpec

DISCORD_CREDENTIALS = {
    "discord": CredentialSpec(
        env_var="DISCORD_BOT_TOKEN",
        tools=[
            "discord_list_guilds",
            "discord_list_channels",
            "discord_send_message",
            "discord_get_messages",
        ],
        required=True,
        startup_required=False,
        help_url="https://discord.com/developers/applications",
        description="Discord Bot Token",
        aden_supported=True,
        aden_provider_name="discord",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Discord Bot Token:
1. Go to https://discord.com/developers/applications
2. Create a new application or select an existing one
3. Go to the "Bot" section in the sidebar
4. Click "Add Bot" if you haven't already
5. Copy the token (click "Reset Token" if needed)
6. Invite the bot to your server via OAuth2 → URL Generator
   - Scopes: bot
   - Permissions: Send Messages, Read Message History, View Channels""",
        health_check_endpoint="https://discord.com/api/v10/users/@me",
        health_check_method="GET",
        credential_id="discord",
        credential_key="access_token",
    ),
}
