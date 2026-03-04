"""
Lusha credentials.

Contains credentials for the Lusha B2B data API.
Requires LUSHA_API_KEY.
"""

from .base import CredentialSpec

LUSHA_CREDENTIALS = {
    "lusha_api_key": CredentialSpec(
        env_var="LUSHA_API_KEY",
        tools=[
            "lusha_enrich_person",
            "lusha_enrich_company",
            "lusha_search_contacts",
            "lusha_search_companies",
            "lusha_get_usage",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.lusha.com/",
        description="Lusha API key for B2B contact and company enrichment",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Lusha API access:
1. Go to dashboard.lusha.com > Enrich > API
2. Copy your API key
3. Set environment variable:
   export LUSHA_API_KEY=your-api-key""",
        health_check_endpoint="https://api.lusha.com/account/usage",
        credential_id="lusha_api_key",
        credential_key="api_key",
    ),
}
