"""
Lusha tool credentials.

Contains credentials for Lusha API integration.
"""

from .base import CredentialSpec

LUSHA_CREDENTIALS = {
    "lusha": CredentialSpec(
        env_var="LUSHA_API_KEY",
        tools=[
            "lusha_enrich_person",
            "lusha_enrich_company",
            "lusha_search_people",
            "lusha_search_companies",
            "lusha_get_signals",
            "lusha_get_account_usage",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.lusha.com/apis/openapi",
        description="Lusha API key for B2B contact and company enrichment",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Lusha API key:
1. Sign up or log in at https://www.lusha.com/
2. Open your Lusha dashboard and navigate to API settings
3. Generate/copy your API key
4. Add it as LUSHA_API_KEY

Note: Lusha API access and credits depend on your Lusha plan.
Trial accounts include a limited monthly credit allotment.""",
        # Health check configuration
        health_check_endpoint="https://api.lusha.com/account/usage",
        health_check_method="GET",
        # Credential store mapping
        credential_id="lusha",
        credential_key="api_key",
    ),
}
