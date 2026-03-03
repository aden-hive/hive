# Redis Tool for Aden Hive

Provides access to Redis for agent state persistence and heavy payload orchestration.

## Features

- **redis_set**: Store a payload in Redis with a TTL (time-to-live).
- **redis_get**: Retrieve a payload by key.
- **redis_ping**: Diagnostic health check for the Redis connection.

## Setup

Set the `REDIS_URL` environment variable:

```bash
export REDIS_URL="redis://localhost:6379/0"
```

Or configure it via the Credential Store using the `redis` credential ID.

## Security

- Securely handles credentials via `CredentialStoreAdapter`.
- Uses asynchronous client (`redis.asyncio`).
- TTL enforced on all stored payloads to prevent memory leaks.
