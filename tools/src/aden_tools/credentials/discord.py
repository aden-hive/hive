"""Discord Bot API credential specification."""

from aden_tools.credentials.base import CredentialSpec

discord_credential_spec = CredentialSpec(
    env_var="DISCORD_BOT_TOKEN",
    tools=[
        "discord_send_message",
        "discord_read_messages",
        "discord_list_channels",
        "discord_add_reaction",
    ],
    node_types=[],
    required=True,
    startup_required=False,
    help_url="https://discord.com/developers/applications",
    description="Discord bot token for API access",
    direct_api_key_supported=True,
    api_key_instructions="""To get a Discord bot token:
1. Go to https://discord.com/developers/applications
2. Click "New Application" and give it a name
3. Navigate to the "Bot" section in the left sidebar
4. Click "Add Bot" and confirm
5. Under "Token", click "Copy" to get your bot token
6. Enable required intents: Message Content Intent
7. Generate OAuth2 URL with bot scope and required permissions
8. Invite bot to your server using the generated URL""",
    health_check_endpoint="https://discord.com/api/v10/users/@me",
    health_check_method="GET",
    credential_id="discord",
    credential_key="bot_token",
)
