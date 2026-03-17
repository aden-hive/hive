"""
Tines credentials.

Contains credentials for the Tines security automation API.
Requires TINES_DOMAIN and TINES_API_KEY.
"""

from .base import CredentialSpec

TINES_CREDENTIALS = {
    "tines_domain": CredentialSpec(
        env_var="TINES_DOMAIN",
        tools=[
            "tines_list_stories",
            "tines_get_story",
            "tines_list_actions",
            "tines_get_action",
            "tines_get_action_logs",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.tines.com/api/authentication/",
        description="Tines tenant domain (e.g. 'your-tenant.tines.com')",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Tines API access:
1. Go to your Tines tenant > Settings > API Keys
2. Create a new API key
3. Set environment variables:
   export TINES_DOMAIN=your-tenant.tines.com
   export TINES_API_KEY=your-api-key""",
        health_check_endpoint="",
        credential_id="tines_domain",
        credential_key="api_key",
    ),
    "tines_api_key": CredentialSpec(
        env_var="TINES_API_KEY",
        tools=[
            "tines_list_stories",
            "tines_get_story",
            "tines_list_actions",
            "tines_get_action",
            "tines_get_action_logs",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.tines.com/api/authentication/",
        description="Tines API key for authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See TINES_DOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="tines_api_key",
        credential_key="api_key",
    ),
}
