"""
Mailchimp tool credentials.
Contains credentials for Mailchimp Marketing API integration.
"""

from __future__ import annotations

from .base import CredentialSpec

MAILCHIMP_CREDENTIALS = {
    "mailchimp": CredentialSpec(
        env_var="MAILCHIMP_API_KEY",
        tools=[
            "mailchimp_ping",
            "mailchimp_list_audiences",
            "mailchimp_get_audience",
            "mailchimp_list_members",
            "mailchimp_get_member",
            "mailchimp_add_or_update_member",
            "mailchimp_update_member_status",
            "mailchimp_delete_member",
            "mailchimp_list_campaigns",
            "mailchimp_get_campaign_report",
            "mailchimp_send_campaign",
        ],
        required=True,
        startup_required=False,
        help_url="https://admin.mailchimp.com/account/api/",
        description="Mailchimp API key for audiences, members, and campaigns management",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Mailchimp API key:
1. Log in to Mailchimp
2. Go to Account → Extras → API keys
3. Click 'Create A Key'
4. Copy the key and set it as MAILCHIMP_API_KEY""",
        health_check_endpoint="",
        health_check_method="GET",
        credential_id="mailchimp",
        credential_key="api_key",
    ),
}

