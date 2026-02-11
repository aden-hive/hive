from .base import CredentialSpec

SNOWFLAKE_CREDENTIALS = {
    "snowflake_account": CredentialSpec(
        env_var="SNOWFLAKE_ACCOUNT",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Snowflake Account Identifier (e.g. xy12345.us-east-1)",
        help_url="https://docs.snowflake.com/en/user-guide/admin-account-identifier",
        required=True,
    ),
    "snowflake_user": CredentialSpec(
        env_var="SNOWFLAKE_USER",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Snowflake Username",
        required=True,
    ),
    "snowflake_private_key": CredentialSpec(
        env_var="SNOWFLAKE_PRIVATE_KEY",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Snowflake Private Key (PEM format)",
        help_url="https://docs.snowflake.com/en/user-guide/key-pair-auth",
        required=True,
    ),
    "snowflake_warehouse": CredentialSpec(
        env_var="SNOWFLAKE_WAREHOUSE",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Default Snowflake Compute Warehouse",
        required=False,
    ),
    "snowflake_database": CredentialSpec(
        env_var="SNOWFLAKE_DATABASE",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Default Snowflake Database",
        required=False,
    ),
    "snowflake_schema": CredentialSpec(
        env_var="SNOWFLAKE_SCHEMA",
        tools=["snowflake_query", "snowflake_describe", "snowflake_insert"],
        description="Default Snowflake Schema",
        required=False,
    ),
}
