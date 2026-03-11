"""
Vibe Prospecting credentials.

Contains credentials for the Vibe Prospecting (Explorium) API.
Requires VIBEPROSPECTING_API_KEY.
"""

from .base import CredentialSpec

VIBEPROSPECTING_CREDENTIALS = {
    "vibeprospecting": CredentialSpec(
        env_var="VIBEPROSPECTING_API_KEY",
        tools=[
            "vibeprospecting_search_companies",
            "vibeprospecting_enrich_company",
            "vibeprospecting_search_prospects",
            "vibeprospecting_enrich_prospect",
            "vibeprospecting_match_company",
            "vibeprospecting_match_prospect",
            "vibeprospecting_company_statistics",
            "vibeprospecting_autocomplete_company",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.explorium.ai/docs/getting-started",
        description="Vibe Prospecting API key for B2B prospecting and data enrichment",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Vibe Prospecting API access:
1. Sign up at https://www.vibeprospecting.ai/
2. Navigate to your account settings or API section
3. Generate an API key
4. Grant necessary permissions for business and prospect data access
5. Set environment variable:
   export VIBEPROSPECTING_API_KEY=your-api-key""",
        health_check_endpoint="https://api.explorium.ai/v1/businesses/stats",
        credential_id="vibeprospecting",
        credential_key="api_key",
    ),
}