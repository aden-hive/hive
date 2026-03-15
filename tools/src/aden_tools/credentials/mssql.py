"""
Microsoft SQL Server connection credentials.

Contains credentials for connecting to Microsoft SQL Server instances.
Requires MSSQL_SERVER, MSSQL_DATABASE, MSSQL_USERNAME, and MSSQL_PASSWORD.
"""

from .base import CredentialSpec

MSSQL_CREDENTIALS = {
    "mssql_server": CredentialSpec(
        env_var="MSSQL_SERVER",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc",
        description="Microsoft SQL Server hostname or IP address",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Microsoft SQL Server access:
1. Ensure you have a running SQL Server instance (local, Azure SQL, or remote)
2. Install the ODBC driver: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
3. Set environment variables:
   export MSSQL_SERVER=your-server-hostname
   export MSSQL_DATABASE=your-database-name
   export MSSQL_USERNAME=your-username
   export MSSQL_PASSWORD=your-password""",
        health_check_endpoint="",
        credential_id="mssql_server",
        credential_key="api_key",
    ),
    "mssql_database": CredentialSpec(
        env_var="MSSQL_DATABASE",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc",
        description="Microsoft SQL Server database name",
        direct_api_key_supported=True,
        api_key_instructions="See MSSQL_SERVER instructions above.",
        health_check_endpoint="",
        credential_id="mssql_database",
        credential_key="api_key",
    ),
    "mssql_username": CredentialSpec(
        env_var="MSSQL_USERNAME",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc",
        description="Microsoft SQL Server login username",
        direct_api_key_supported=True,
        api_key_instructions="See MSSQL_SERVER instructions above.",
        health_check_endpoint="",
        credential_id="mssql_username",
        credential_key="api_key",
    ),
    "mssql_password": CredentialSpec(
        env_var="MSSQL_PASSWORD",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc",
        description="Microsoft SQL Server login password",
        direct_api_key_supported=True,
        api_key_instructions="See MSSQL_SERVER instructions above.",
        health_check_endpoint="",
        credential_id="mssql_password",
        credential_key="api_key",
    ),
}
