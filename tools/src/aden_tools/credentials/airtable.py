"""
Airtable tool credentials.

Contains credentials for Airtable bases and records integration.
"""

from .base import CredentialSpec

AIRTABLE_CREDENTIALS = {
    "airtable": CredentialSpec(
        env_var="AIRTABLE_API_TOKEN",
        tools=[
            "airtable_list_bases",
            "airtable_list_tables",
            "airtable_list_records",
            "airtable_create_record",
            "airtable_update_record",
        ],
        required=True,
        startup_required=False,
        help_url="https://airtable.com/create/tokens",
        description="Airtable Personal Access Token",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Airtable Personal Access Token:
1. Go to https://airtable.com/create/tokens
2. Click "Create new token"
3. Name your token and add scopes: schema.bases:read, data.records:read, data.records:write
4. Add base access (or all bases)
5. Copy the token and set AIRTABLE_API_TOKEN environment variable""",
        health_check_endpoint="https://api.airtable.com/v0/meta/bases",
        health_check_method="GET",
        credential_id="airtable",
        credential_key="access_token",
    ),
}
