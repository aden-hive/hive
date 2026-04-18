"""
SavvyCal credentials.

Contains credentials for the SavvyCal scheduling API integration.
"""

from .base import CredentialSpec

SAVVYCAL_CREDENTIALS = {
    "savvycal": CredentialSpec(
        env_var="SAVVYCAL_API_KEY",
        tools=[
            "savvycal_list_links",
            "savvycal_get_link",
            "savvycal_create_link",
            "savvycal_update_link",
            "savvycal_delete_link",
            "savvycal_list_bookings",
            "savvycal_get_booking",
            "savvycal_cancel_booking",
        ],
        required=True,
        startup_required=False,
        help_url="https://savvycal.com/users/settings/developer",
        description="SavvyCal personal API key for scheduling link and booking management",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a SavvyCal API key:
1. Log in to your SavvyCal account at https://savvycal.com
2. Go to Settings > Developer (https://savvycal.com/users/settings/developer)
3. Click "New Personal Access Token"
4. Give the token a name (e.g., "Hive Agent")
5. Copy the token — it won't be shown again
6. Set as environment variable:
   export SAVVYCAL_API_KEY=your_token_here""",
        health_check_endpoint="https://api.savvycal.com/v1/me",
        health_check_method="GET",
        credential_id="savvycal",
        credential_key="api_key",
    ),
}
