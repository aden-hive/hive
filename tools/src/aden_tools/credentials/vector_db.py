"""
Vector Database tool credentials.

Contains credentials for Vector DB integration (ChromaDB).
"""

from .base import CredentialSpec

VECTOR_DB_CREDENTIALS = {
    "vector_db": CredentialSpec(
        env_var="CHROMA_PERSIST_DIR",  # Using persist dir as the primary "credential" env var
        tools=[
            "vector_db_upsert",
            "vector_db_search",
            "vector_db_delete",
            "vector_db_count",
        ],
        required=False,  # Can use defaults
        startup_required=False,
        description="ChromaDB Persistence Directory",
        help_url="https://docs.trychroma.com/",
        # Auth method support
        direct_api_key_supported=False,
        # Health check configuration
        health_check_endpoint=None,  # Local file based
        # Credential store mapping
        credential_id="vector_db",
        credential_key="persist_directory",
    ),
}
