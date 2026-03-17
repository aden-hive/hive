"""
Pinecone credentials.

Contains credentials for Pinecone vector database operations.
"""

from .base import CredentialSpec

PINECONE_CREDENTIALS = {
    "pinecone": CredentialSpec(
        env_var="PINECONE_API_KEY",
        tools=[
            "pinecone_list_indexes",
            "pinecone_create_index",
            "pinecone_describe_index",
            "pinecone_delete_index",
            "pinecone_upsert_vectors",
            "pinecone_query_vectors",
            "pinecone_fetch_vectors",
            "pinecone_delete_vectors",
            "pinecone_index_stats",
        ],
        required=True,
        startup_required=False,
        help_url="https://app.pinecone.io/",
        description="API key for Pinecone vector database operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Pinecone API key:
1. Go to https://app.pinecone.io/ and sign up or log in
2. Navigate to 'API Keys' in the left sidebar
3. Click 'Create API Key' or copy the default key
4. Set the environment variable:
   export PINECONE_API_KEY=your-api-key""",
        health_check_endpoint="https://api.pinecone.io/indexes",
        credential_id="pinecone",
        credential_key="api_key",
    ),
}
