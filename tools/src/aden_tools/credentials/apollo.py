"""
Apollo.io tool credentials.

Contains credentials for Apollo.io API integration.
"""

from .base import CredentialSpec

APOLLO_CREDENTIALS = {
    "apollo": CredentialSpec(
        env_var="APOLLO_API_KEY",
        tools=[
            "apollo_enrich_person",
            "apollo_enrich_company",
            "apollo_search_people",
            "apollo_search_companies",
        ],
        required=True,
        startup_required=False,
        help_url="https://apolloio.github.io/apollo-api-docs/",
        description="Apollo.io API key for contact and company data enrichment",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an Apollo.io API key:
1. Sign up or log in at https://app.apollo.io/
2. Go to Settings > Integrations > API
3. Click "Connect" to generate your API key
4. Copy the API key

Note: Apollo uses export credits for enrichment:
- Free plan: 10 credits/month
- Basic ($49/user/mo): 1,000 credits/month
- Professional ($79/user/mo): 2,000 credits/month
- Overage: $0.20/credit""",
        # Health check configuration
        health_check_endpoint="https://api.apollo.io/v1/auth/health",
        health_check_method="GET",
        # Credential store mapping
        credential_id="apollo",
        credential_key="api_key",
    ),
}
