"""
MongoDB credentials.

Contains credentials for MongoDB Atlas Data API.
Requires MONGODB_DATA_API_URL, MONGODB_API_KEY, and MONGODB_DATA_SOURCE.
"""

from .base import CredentialSpec

MONGODB_CREDENTIALS = {
    "mongodb_url": CredentialSpec(
        env_var="MONGODB_DATA_API_URL",
        tools=[
            "mongodb_find",
            "mongodb_find_one",
            "mongodb_insert_one",
            "mongodb_update_one",
            "mongodb_delete_one",
            "mongodb_aggregate",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.mongodb.com/docs/atlas/app-services/data-api/",
        description="MongoDB Atlas Data API URL (e.g. https://data.mongodb-api.com/app/APP_ID/endpoint/data/v1)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up MongoDB Atlas Data API access:
1. Go to MongoDB Atlas > App Services > Data API
2. Enable the Data API and copy the URL Endpoint
3. Create an API key
4. Set environment variables:
   export MONGODB_DATA_API_URL=your-data-api-url
   export MONGODB_API_KEY=your-api-key
   export MONGODB_DATA_SOURCE=Cluster0""",
        health_check_endpoint="",
        credential_id="mongodb_url",
        credential_key="api_key",
    ),
    "mongodb_api_key": CredentialSpec(
        env_var="MONGODB_API_KEY",
        tools=[
            "mongodb_find",
            "mongodb_find_one",
            "mongodb_insert_one",
            "mongodb_update_one",
            "mongodb_delete_one",
            "mongodb_aggregate",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.mongodb.com/docs/atlas/app-services/data-api/",
        description="MongoDB Atlas Data API key",
        direct_api_key_supported=True,
        api_key_instructions="""See MONGODB_DATA_API_URL instructions above.""",
        health_check_endpoint="",
        credential_id="mongodb_api_key",
        credential_key="api_key",
    ),
    "mongodb_data_source": CredentialSpec(
        env_var="MONGODB_DATA_SOURCE",
        tools=[
            "mongodb_find",
            "mongodb_find_one",
            "mongodb_insert_one",
            "mongodb_update_one",
            "mongodb_delete_one",
            "mongodb_aggregate",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.mongodb.com/docs/atlas/app-services/data-api/",
        description="MongoDB cluster name (e.g. 'Cluster0')",
        direct_api_key_supported=True,
        api_key_instructions="""See MONGODB_DATA_API_URL instructions above.""",
        health_check_endpoint="",
        credential_id="mongodb_data_source",
        credential_key="api_key",
    ),
}
