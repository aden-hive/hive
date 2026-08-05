"""
IPInfo tool credentials.

Contains credentials for ipinfo.io API integration.
"""

from .base import CredentialSpec

IPINFO_CREDENTIALS = {
    "ipinfo": CredentialSpec(
        env_var="IPINFO_TOKEN",
        tools=["ipinfo_get_ip_details", "ipinfo_get_my_ip", "ipinfo_bulk_lookup"],
        required=False,
        startup_required=False,
        help_url="https://ipinfo.io/signup",
        description="IPInfo API token for IP geolocation (free tier: 50K req/month)",
        direct_api_key_supported=True,
        api_key_instructions=(
            "To get an IPInfo API token:\n"
            "1. Go to https://ipinfo.io/signup\n"
            "2. Sign up for a free account\n"
            "3. Copy your API token from the dashboard\n"
            "4. Set the IPINFO_TOKEN environment variable\n"
            "\n"
            "Free tier includes 50,000 requests/month with commercial use allowed."
        ),
        credential_id="ipinfo",
    ),
}
