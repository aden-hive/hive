"""
Mailchimp tool credentials.

Contains credentials for Mailchimp email marketing, audience management,
and campaign tracking integration.
"""

from .base import CredentialSpec

MAILCHIMP_CREDENTIALS = {
    "mailchimp": CredentialSpec(
        env_var="MAILCHIMP_API_KEY",
        tools=[
            "mailchimp_get_audiences",
            "mailchimp_get_audience",
            "mailchimp_add_member",
            "mailchimp_get_member",
            "mailchimp_update_member",
            "mailchimp_list_campaigns",
            "mailchimp_get_campaign_report",
        ],
        required=True,
        startup_required=False,
        help_url="https://admin.mailchimp.com/account/api/",
        description="Mailchimp API key for audience, member, and campaign management",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Mailchimp API key:
1. Log in to your Mailchimp account
2. Click on your profile in the bottom left, then click 'Account & billing'
3. Click on the 'Extras' drop-down and choose 'API keys'
4. Click 'Create A Key'
5. Give the key a descriptive name (e.g., 'Hive Agent')
6. Copy the API key (format: <key>-<dc>, where <dc> is your data center, e.g., us1)
7. Store it securely - you won't be able to see it again!""",
        # Health check configuration
        health_check_endpoint="https://{dc}.api.mailchimp.com/3.0/ping",
        health_check_method="GET",
        # Credential store mapping
        credential_id="mailchimp",
        credential_key="api_key",
    ),
}
