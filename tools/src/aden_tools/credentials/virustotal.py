"""
VirusTotal tool credentials.
Contains credentials for VirusTotal threat intelligence integration.
"""

from .base import CredentialSpec

VIRUSTOTAL_CREDENTIALS = {
    "virustotal": CredentialSpec(
        env_var="VIRUSTOTAL_API_KEY",
        tools=[
            "vt_scan_ip",
            "vt_scan_domain",
            "vt_scan_hash",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.virustotal.com/gui/join-us",
        description="VirusTotal API key for threat intelligence lookups",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get your VirusTotal API key:
1. Go to https://www.virustotal.com/gui/join-us and create a free community account.
2. Verify your email address and log in.
3. Click on your profile icon in the top right corner and select "API Key".
4. Copy the alphanumeric API key provided.
Note: Free tier allows 500 requests/day and 4 requests/minute.""",
        # Health check configuration
        health_check_endpoint="https://www.virustotal.com/api/v3/domains/google.com",
        health_check_method="GET",
        # Credential store mapping
        credential_id="virustotal",
        credential_key="api_key",
        credential_group="",
    ),
}
