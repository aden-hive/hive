"""
Redis tool credentials.
"""

from .base import CredentialSpec

REDIS_CREDENTIALS = {
    "redis": CredentialSpec(
        env_var="REDIS_URL",
        tools=[
            "redis_set",
            "redis_get",
            "redis_ping",
        ],
        required=True,
        startup_required=False,
        description="Redis connection URL for agent state persistence and heavy payload orchestration.",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Provide a Redis connection string:

redis://:password@host:port/db

Example:
redis://localhost:6379/0""",
        credential_id="redis",
        credential_key="connection_url",
    ),
}
