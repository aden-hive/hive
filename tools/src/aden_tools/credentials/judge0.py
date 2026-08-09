"""
Judge0 code execution engine credentials.

Contains credentials for Judge0 CE API on RapidAPI.
"""

from .base import CredentialSpec

JUDGE0_CREDENTIALS = {
    "judge0": CredentialSpec(
        env_var="JUDGE0_API_KEY",
        tools=[
            "judge0_list_languages",
            "judge0_run_code",
            "judge0_submit",
            "judge0_get_submission",
        ],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://rapidapi.com/judge0-official/api/judge0-ce",
        description="API key for Judge0 code execution engine (RapidAPI X-RapidAPI-Key)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Judge0 CE API key from RapidAPI:
1. Go to https://rapidapi.com/judge0-official/api/judge0-ce
2. Sign up or log in to RapidAPI
3. Subscribe to a plan (free tier available with 50 requests/day)
4. Go to the "Endpoints" tab
5. Copy the X-RapidAPI-Key from the header parameters
6. Store it securely

Note: Self-hosted Judge0 instances are also supported via JUDGE0_BASE_URL
environment variable override. In that case, the RapidAPI key requirement
can be bypassed depending on the self-hosted instance's auth configuration.""",
        # Health check configuration
        health_check_endpoint="https://judge0-ce.p.rapidapi.com/languages",
        health_check_method="GET",
        # Credential store mapping
        credential_id="judge0",
        credential_key="api_key",
    ),
}
