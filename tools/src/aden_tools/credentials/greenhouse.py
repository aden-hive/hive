"""
Greenhouse credentials.

Contains credentials for Greenhouse ATS & recruiting.
Requires GREENHOUSE_API_TOKEN.
"""

from .base import CredentialSpec

GREENHOUSE_CREDENTIALS = {
    "greenhouse_token": CredentialSpec(
        env_var="GREENHOUSE_API_TOKEN",
        tools=[
            "greenhouse_list_jobs",
            "greenhouse_get_job",
            "greenhouse_list_candidates",
            "greenhouse_get_candidate",
            "greenhouse_list_applications",
            "greenhouse_get_application",
            "greenhouse_list_offers",
            "greenhouse_add_candidate_note",
            "greenhouse_list_scorecards",
        ],
        required=True,
        startup_required=False,
        help_url="https://support.greenhouse.io/hc/en-us/articles/202842799-Harvest-API",
        description="Greenhouse Harvest API token for ATS access",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Greenhouse Harvest API access:
1. Go to Greenhouse > Configure > Dev Center > API Credential Management
2. Click 'Create New API Key'
3. Select 'Harvest' as the API type
4. Set permissions (at minimum: Jobs, Candidates, Applications read access)
5. Set environment variable:
   export GREENHOUSE_API_TOKEN=your-api-token""",
        health_check_endpoint="https://harvest.greenhouse.io/v1/jobs?per_page=1",
        credential_id="greenhouse_token",
        credential_key="api_key",
    ),
}
