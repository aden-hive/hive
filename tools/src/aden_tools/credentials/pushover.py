"""
Pushover credentials.

Contains credentials for Pushover push notification service.
"""

from .base import CredentialSpec

PUSHOVER_CREDENTIALS = {
    "pushover": CredentialSpec(
        env_var="PUSHOVER_API_TOKEN",
        tools=[
            "pushover_send",
            "pushover_validate_user",
            "pushover_list_sounds",
            "pushover_check_receipt",
        ],
        required=True,
        startup_required=False,
        help_url="https://pushover.net/apps/build",
        description="Pushover application API token",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Pushover API token:
1. Go to https://pushover.net/ and create an account
2. Go to https://pushover.net/apps/build
3. Create a new application/API token
4. Copy the API Token/Key
5. Your User Key is on the main dashboard at https://pushover.net/
6. Set environment variable:
   export PUSHOVER_API_TOKEN=your-app-token""",
        health_check_endpoint="",
        credential_id="pushover",
        credential_key="api_key",
    ),
}
