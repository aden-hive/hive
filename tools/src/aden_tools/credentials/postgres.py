"""
PostgreSQL tool credentials.
"""

from .base import CredentialSpec

POSTGRES_CREDENTIALS = {
    "postgres": CredentialSpec(
        env_var="DATABASE_URL",
        tools=[
            "pg_query",
            "pg_list_schemas",
            "pg_list_tables",
            "pg_describe_table",
            "pg_explain",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.postgresql.org/docs/current/libpq-connect.html",
        description="PostgreSQL connection string (postgresql://user:pass@host:port/db)",
        aden_supported=True,
        aden_provider_name="postgres",
        direct_api_key_supported=False,
        api_key_instructions="""Provide a PostgreSQL connection string:

postgresql://user:password@host:port/database

Example:
postgresql://postgres:secret@localhost:5432/mydb

The database user should have read-only permissions.""",
        health_check_endpoint=None,
        health_check_method=None,
        credential_id="postgres",
        credential_key="database_url",
    ),
}
