"""
Snowflake credentials.

Contains credentials for the Snowflake SQL REST API.
Requires SNOWFLAKE_ACCOUNT and SNOWFLAKE_TOKEN.
"""

from .base import CredentialSpec

SNOWFLAKE_CREDENTIALS = {
    "snowflake_account": CredentialSpec(
        env_var="SNOWFLAKE_ACCOUNT",
        tools=[
            "snowflake_execute_sql",
            "snowflake_get_statement_status",
            "snowflake_cancel_statement",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.snowflake.com/en/developer-guide/sql-api/index",
        description="Snowflake account identifier (e.g. 'xy12345.us-east-1')",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Snowflake SQL API access:
1. Get your Snowflake account identifier from your account URL
2. Generate a JWT or OAuth token for authentication
3. Set environment variables:
   export SNOWFLAKE_ACCOUNT=your-account-id
   export SNOWFLAKE_TOKEN=your-jwt-or-oauth-token
   export SNOWFLAKE_WAREHOUSE=your-warehouse (optional)
   export SNOWFLAKE_DATABASE=your-database (optional)""",
        health_check_endpoint="",
        credential_id="snowflake_account",
        credential_key="api_key",
    ),
    "snowflake_token": CredentialSpec(
        env_var="SNOWFLAKE_TOKEN",
        tools=[
            "snowflake_execute_sql",
            "snowflake_get_statement_status",
            "snowflake_cancel_statement",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.snowflake.com/en/developer-guide/sql-api/authenticating",
        description="Snowflake JWT or OAuth token for API authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See SNOWFLAKE_ACCOUNT instructions above.""",
        health_check_endpoint="",
        credential_id="snowflake_token",
        credential_key="api_key",
    ),
}
