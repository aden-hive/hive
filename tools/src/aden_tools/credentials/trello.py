"""
Trello credentials.

Contains credentials for Trello board, list, and card management.
Trello requires both TRELLO_API_KEY and TRELLO_TOKEN.
"""

from .base import CredentialSpec

TRELLO_CREDENTIALS = {
    "trello_key": CredentialSpec(
        env_var="TRELLO_API_KEY",
        tools=[
            "trello_list_boards",
            "trello_get_member",
            "trello_list_lists",
            "trello_list_cards",
            "trello_create_card",
            "trello_move_card",
            "trello_update_card",
            "trello_add_comment",
            "trello_add_attachment",
        ],
        required=True,
        startup_required=False,
        help_url="https://trello.com/power-ups/admin",
        description="Trello API key (also set TRELLO_TOKEN for authentication)",
        direct_api_key_supported=True,
        api_key_instructions="""To get Trello credentials:
1. Go to https://trello.com/power-ups/admin
2. Select your Power-Up or create one
3. Copy the API Key
4. Generate a token via the authorize URL
5. Set environment variables:
   export TRELLO_API_KEY=your-api-key
   export TRELLO_TOKEN=your-token""",
        health_check_endpoint="https://api.trello.com/1/members/me",
        credential_id="trello_key",
        credential_key="api_key",
    ),
    "trello_token": CredentialSpec(
        env_var="TRELLO_API_TOKEN",
        tools=[
            "trello_list_boards",
            "trello_get_member",
            "trello_list_lists",
            "trello_list_cards",
            "trello_create_card",
            "trello_move_card",
            "trello_update_card",
            "trello_add_comment",
            "trello_add_attachment",
        ],
        required=True,
        startup_required=False,
        help_url="https://trello.com/power-ups/admin",
        description="Trello API token for authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See TRELLO_API_KEY instructions above.""",
        health_check_endpoint="https://api.trello.com/1/members/me",
        credential_id="trello_token",
        credential_key="api_key",
    ),
}
