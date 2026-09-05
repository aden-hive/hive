"""
IPInfo tool credentials.
Contains credentials for IPInfo IP geolocation integration.
"""

from .base import CredentialSpec

IPINFO_CREDENTIALS = {
    "ipinfo": CredentialSpec(
        env_var="IPINFO_TOKEN",
        tools=[
            "ipinfo_get_ip_details",
            "ipinfo_get_my_ip",
        ],
        required=True,
        startup_required=False,
        help_url="https://ipinfo.io/account/token",
        description="IPInfo API token for IP geolocation and network intelligence",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an IPInfo token:
1. Sign up for free at https://ipinfo.io/signup
2. Go to your dashboard at https://ipinfo.io/account/token
3. Copy your access token
4. Set it as IPINFO_TOKEN""",
        health_check_endpoint="https://ipinfo.io/8.8.8.8",
        health_check_method="GET",
        credential_id="ipinfo",
        credential_key="token",
    ),
}
