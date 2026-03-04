"""
Airtable credentials.

Contains credentials for the Airtable Web API.
Requires AIRTABLE_PAT (Personal Access Token).
"""

from .base import CredentialSpec

AIRTABLE_CREDENTIALS = {
    "airtable_pat": CredentialSpec(
        env_var="AIRTABLE_PAT",
        tools=[
            "airtable_list_records",
            "airtable_get_record",
            "airtable_create_records",
            "airtable_update_records",
            "airtable_list_bases",
            "airtable_get_base_schema",
        ],
        required=True,
        startup_required=False,
        help_url="https://airtable.com/create/tokens",
        description="Airtable Personal Access Token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Airtable API access:
1. Go to https://airtable.com/create/tokens
2. Create a new Personal Access Token
3. Grant scopes: data.records:read, data.records:write, schema.bases:read
4. Select the bases to grant access to
5. Set environment variable:
   export AIRTABLE_PAT=your-personal-access-token""",
        health_check_endpoint="",
        credential_id="airtable_pat",
        credential_key="api_key",
    ),
}
