"""
Cloudflare tool credentials.

Contains credentials for Cloudflare API integration.
"""

from .base import CredentialSpec

CLOUDFLARE_CREDENTIALS = {
    "cloudflare": CredentialSpec(
        env_var="CLOUDFLARE_API_TOKEN",
        tools=[
            "cloudflare_list_zones",
            "cloudflare_get_zone",
            "cloudflare_list_dns_records",
            "cloudflare_create_dns_record",
            "cloudflare_update_dns_record",
            "cloudflare_delete_dns_record",
            "cloudflare_purge_cache",
        ],
        required=True,
        startup_required=False,
        help_url="https://dash.cloudflare.com/profile/api-tokens",
        description="Cloudflare API Token",
        aden_supported=False,
        aden_provider_name=None,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Cloudflare API Token:
1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use the "Edit zone DNS" template or create a custom token
4. Select permissions: Zone:Read, DNS:Edit, Cache Purge:Purge
5. Choose zone resources (all zones or specific ones)
6. Click "Continue to summary" then "Create Token"
7. Copy the token and set as CLOUDFLARE_API_TOKEN""",
        health_check_endpoint="https://api.cloudflare.com/client/v4/user/tokens/verify",
        health_check_method="GET",
        credential_id="cloudflare",
        credential_key="api_token",
    ),
}
