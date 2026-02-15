"""
Attio tool credentials.

Contains credentials for Attio CRM integration.
"""

from .base import CredentialSpec

ATTIO_CREDENTIALS = {
    "attio": CredentialSpec(
        env_var="ATTIO_API_KEY",
        tools=[
            "attio_record_list",
            "attio_record_get",
            "attio_record_create",
            "attio_record_update",
            "attio_record_assert",
            "attio_list_lists",
            "attio_list_entries_get",
            "attio_list_entry_create",
            "attio_list_entry_delete",
            "attio_task_create",
            "attio_task_list",
            "attio_task_get",
            "attio_task_delete",
            "attio_members_list",
            "attio_member_get",
        ],
        required=True,
        startup_required=False,
        help_url="https://attio.com/help/apps/other-apps/generating-an-api-key",
        description="Attio API key for CRM integration",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an Attio API key:
1. Go to Attio Settings > Developers > Access tokens
2. Click "Generate new token"
3. Name your token (e.g., "Hive Agent")
4. Select required scopes:
   - record_permission:read-write
   - object_configuration:read
   - list_entry:read-write
   - list_configuration:read
   - task:read-write
   - user_management:read
5. Copy the generated token""",
        # Health check configuration
        health_check_endpoint="https://api.attio.com/v2/workspace_members",
        health_check_method="GET",
        # Credential store mapping
        credential_id="attio",
        credential_key="api_key",
    ),
}
