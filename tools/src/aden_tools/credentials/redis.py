"""
Redis credentials.

Contains credentials for Redis in-memory data store.
"""

from .base import CredentialSpec

REDIS_CREDENTIALS = {
    "redis": CredentialSpec(
        env_var="REDIS_URL",
        tools=[
            "redis_get",
            "redis_set",
            "redis_delete",
            "redis_keys",
            "redis_hset",
            "redis_hgetall",
            "redis_lpush",
            "redis_lrange",
            "redis_publish",
            "redis_info",
            "redis_ttl",
        ],
        required=True,
        startup_required=False,
        help_url="https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/",
        description="Redis connection URL (e.g. redis://localhost:6379 or redis://:password@host:6379/0)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Redis:
1. Install Redis locally: brew install redis (macOS) or apt install redis-server (Linux)
2. Or use a hosted service: Redis Cloud (https://redis.com/cloud/), Upstash, etc.
3. Set the connection URL:
   export REDIS_URL=redis://localhost:6379
   export REDIS_URL=redis://:your-password@host:port/db-number""",
        health_check_endpoint="",
        credential_id="redis",
        credential_key="url",
    ),
}
