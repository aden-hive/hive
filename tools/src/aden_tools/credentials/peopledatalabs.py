"""
People Data Labs credentials.

Contains credentials for the People Data Labs API.
Requires PDL_API_KEY (API Key).
"""

from .base import CredentialSpec

PEOPLE_DATA_LABS_CREDENTIALS = {
    "people_data_labs": CredentialSpec(
        env_var="PDL_API_KEY",
        tools=[
            "pdl_enrich_person",
            "pdl_search_people",
            "pdl_identify_person",
            "pdl_bulk_enrich_people",
            "pdl_enrich_company",
            "pdl_search_companies",
            "pdl_autocomplete",
            "pdl_clean_company",
            "pdl_clean_location",
            "pdl_clean_school",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.peopledatalabs.com/docs/quickstart",
        description="People Data Labs API key for B2B person and company data enrichment",
        direct_api_key_supported=True,
        api_key_instructions="""To set up People Data Labs API access:
1. Sign up at https://dashboard.peopledatalabs.com/signup
2. Get your API key from the dashboard
3. Free tier includes:
   - 1,000 free API credits
   - Access to 3 billion+ person profiles
   - 100 requests per minute
4. Set environment variable:
   export PDL_API_KEY=your-api-key""",
        health_check_endpoint="https://api.peopledatalabs.com/v5/person/enrich",
        credential_id="people_data_labs",
        credential_key="api_key",
    ),
}