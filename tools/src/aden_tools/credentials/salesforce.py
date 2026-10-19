"""
Salesforce CRM credentials.

Contains credentials for the Salesforce REST API.
Requires SALESFORCE_ACCESS_TOKEN and SALESFORCE_INSTANCE_URL.
"""

from .base import CredentialSpec

SALESFORCE_CREDENTIALS = {
    "salesforce": CredentialSpec(
        env_var="SALESFORCE_ACCESS_TOKEN",
        tools=[
            "salesforce_soql_query",
            "salesforce_get_record",
            "salesforce_create_record",
            "salesforce_update_record",
            "salesforce_describe_object",
            "salesforce_list_objects",
            "salesforce_delete_record",
            "salesforce_search_records",
            "salesforce_get_record_count",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest",
        description="Salesforce OAuth2 Bearer access token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Salesforce REST API access:
1. Create a Connected App in Salesforce Setup
2. Enable OAuth settings and select required scopes (api, full)
3. Use Client Credentials or Username-Password flow to obtain a token
4. Set environment variables:
   export SALESFORCE_ACCESS_TOKEN=your-bearer-token
   export SALESFORCE_INSTANCE_URL=https://your-org.my.salesforce.com""",
        health_check_endpoint="",
        credential_id="salesforce",
        credential_key="api_key",
    ),
    "salesforce_instance_url": CredentialSpec(
        env_var="SALESFORCE_INSTANCE_URL",
        tools=[
            "salesforce_soql_query",
            "salesforce_get_record",
            "salesforce_create_record",
            "salesforce_update_record",
            "salesforce_describe_object",
            "salesforce_list_objects",
            "salesforce_delete_record",
            "salesforce_search_records",
            "salesforce_get_record_count",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest",
        description="Salesforce instance URL (e.g. 'https://your-org.my.salesforce.com')",
        direct_api_key_supported=True,
        api_key_instructions="""See SALESFORCE_ACCESS_TOKEN instructions above.""",
        health_check_endpoint="",
        credential_id="salesforce_instance_url",
        credential_key="api_key",
    ),
}
