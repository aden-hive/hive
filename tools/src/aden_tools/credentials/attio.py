"""
Attio CRM credentials.

Contains credentials for Attio record, list, and task management.
"""

from .base import CredentialSpec

ATTIO_CREDENTIALS = {
    "attio": CredentialSpec(
        env_var="ATTIO_API_KEY",
        tools=[
            "attio_list_objects",
            "attio_list_records",
            "attio_search_records",
            "attio_create_record",
            "attio_list_lists",
            "attio_list_entries",
            "attio_create_note",
            "attio_list_tasks",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.attio.com/rest-api/overview",
        description="Attio API key for CRM record, list, and task management",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Attio API key:
1. Go to https://app.attio.com/settings/developers
2. Click 'Create new integration'
3. Configure required scopes (record_permission:read-write, object_configuration:read)
4. Copy the access token
5. Set the environment variable:
   export ATTIO_API_KEY=your-access-token""",
        health_check_endpoint="https://api.attio.com/v2/self",
        credential_id="attio",
        credential_key="api_key",
    ),
}
