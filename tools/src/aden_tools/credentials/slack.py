"""
Slack tool credentials.

Contains credentials for Slack workspace integration.
"""

from .base import CredentialSpec

SLACK_CREDENTIALS = {
    "slack": CredentialSpec(
        env_var="SLACK_BOT_TOKEN",
        tools=[
            "slack_send_message",
            "slack_list_channels",
            "slack_get_channel_history",
            "slack_add_reaction",
            "slack_get_user_info",
            "slack_update_message",
            "slack_delete_message",
            "slack_schedule_message",
            "slack_create_channel",
            "slack_archive_channel",
            "slack_invite_to_channel",
            "slack_set_channel_topic",
            "slack_remove_reaction",
            "slack_list_users",
            "slack_upload_file",
            "slack_search_messages",
            "slack_get_thread_replies",
            "slack_pin_message",
            "slack_unpin_message",
            "slack_list_pins",
            "slack_add_bookmark",
            "slack_list_scheduled_messages",
            "slack_delete_scheduled_message",
            "slack_send_dm",
            "slack_get_permalink",
            "slack_send_ephemeral",
            "slack_post_blocks",
            "slack_open_modal",
            "slack_update_home_tab",
            "slack_set_status",
            "slack_set_presence",
            "slack_get_presence",
            "slack_create_reminder",
            "slack_list_reminders",
            "slack_delete_reminder",
            "slack_create_usergroup",
            "slack_update_usergroup_members",
            "slack_list_usergroups",
            "slack_list_emoji",
            "slack_create_canvas",
            "slack_edit_canvas",
            "slack_get_messages_for_analysis",
            "slack_trigger_workflow",
            "slack_get_conversation_context",
            "slack_find_user_by_email",
            "slack_kick_user_from_channel",
            "slack_delete_file",
            "slack_get_team_stats",
        ],
        required=True,
        startup_required=False,
        help_url="https://api.slack.com/apps",
        description="Slack Bot Token (starts with xoxb-)",
        # Auth method support
        aden_supported=True,
        aden_provider_name="slack",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Slack Bot Token:
1. Go to https://api.slack.com/apps and click "Create New App"
2. Choose "From scratch" and give your app a name
3. Select the workspace where you want to install the app
4. Go to "OAuth & Permissions" in the sidebar
5. Add the following Bot Token Scopes:
   - channels:read, channels:write, channels:history
   - chat:write, chat:write.public
   - users:read, users:read.email
   - reactions:read, reactions:write
   - files:read, files:write
   - search:read (requires user token)
   - pins:read, pins:write
   - bookmarks:read, bookmarks:write
   - reminders:read, reminders:write
   - usergroups:read, usergroups:write
6. Click "Install to Workspace" and authorize
7. Copy the "Bot User OAuth Token" (starts with xoxb-)""",
        # Health check configuration
        health_check_endpoint="https://slack.com/api/auth.test",
        health_check_method="POST",
        # Credential store mapping
        credential_id="slack",
        credential_key="access_token",
    ),
}
