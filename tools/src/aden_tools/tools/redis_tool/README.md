# Redis Tool

In-memory data store operations for key-value, hash, list, pub/sub, and TTL management.

## Supported Actions

- **redis_get** / **redis_set** / **redis_delete** – Basic key-value operations with optional TTL
- **redis_keys** – Non-blocking key scan with glob patterns (uses SCAN, not KEYS)
- **redis_hset** / **redis_hgetall** – Hash field operations
- **redis_lpush** / **redis_lrange** – List push and range queries
- **redis_publish** – Pub/sub message publishing
- **redis_info** – Server stats (version, memory, connections, keyspace)
- **redis_ttl** – Check remaining TTL on a key

## Setup

Set the connection URL:
```bash
export REDIS_URL=redis://localhost:6379
```

For authenticated instances:
```bash
export REDIS_URL=redis://:your-password@host:6379/0
```

The tool also supports the Hive credential store — store the URL under the `redis` credential key.

## Use Case

Example: "Cache API responses for 5 minutes to avoid rate limits, and publish a notification to the `cache-invalidation` channel when stale entries are cleared."
