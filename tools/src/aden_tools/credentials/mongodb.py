"""
MongoDB tool credentials.
Contains credentials for MongoDB database integration.
"""

from .base import CredentialSpec

MONGODB_CREDENTIALS = {
    "mongodb": CredentialSpec(
        env_var="MONGODB_URI",
        tools=[
            "mongodb_insert_document",
            "mongodb_find_document",
            "mongodb_update_document",
            "mongodb_delete_document",
            "mongodb_list_collections",
            "mongodb_count_documents",
            "mongodb_aggregate",
            "mongodb_ping_database",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.mongodb.com/docs/guides/atlas/connection-string/",
        description="MongoDB Connection String URI for authenticating database connections",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get your MongoDB Connection String:
1. Log in to your MongoDB Atlas dashboard.
2. Click 'Connect' on your cluster.
3. Select 'Drivers' (or 'Connect your application').
4. Copy the connection string (starts with mongodb+srv://).
5. Replace <password> with your actual database user password (ensure no < > brackets remain).""",
        # Health check configuration
        # Note: For databases, health checks are typically done via a driver 'ping' command
        # rather than an HTTP endpoint like Stripe. Left blank for compatibility.
        health_check_endpoint="", 
        health_check_method="",
        # Credential store mapping
        credential_id="mongodb",
        credential_key="uri",
        credential_group="",
    ),
}
