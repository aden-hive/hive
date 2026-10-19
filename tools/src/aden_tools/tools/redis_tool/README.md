# Redis Tool

Key-value, hash, list, pub/sub, and utility operations for Redis via a connection URL.

## Tools

| Tool | Description |
|------|-------------|
| `redis_get` | Get the value of a key |
| `redis_set` | Set a key-value pair with optional TTL |
| `redis_delete` | Delete one or more keys |
| `redis_keys` | List keys matching a pattern (non-blocking SCAN) |
| `redis_hset` | Set a field in a hash |
| `redis_hgetall` | Get all fields and values from a hash |
| `redis_lpush` | Push values to the head of a list |
| `redis_lrange` | Get a range of elements from a list |
| `redis_publish` | Publish a message to a channel |
| `redis_ttl` | Get the time-to-live of a key in seconds |
| `redis_info` | Get Redis server information and statistics |

## Setup

Requires a Redis connection URL:

```bash
export REDIS_URL="redis://localhost:6379"
# With password:
# export REDIS_URL="redis://:yourpassword@host:6379/0"
# With TLS:
# export REDIS_URL="rediss://:yourpassword@host:6379/0"
```

## Usage Examples

### Get and set a key
```python
redis_set(key="user:123:name", value="Alice", ttl=3600)
redis_get(key="user:123:name")
```

### Delete keys
```python
redis_delete(keys="user:123:name, user:123:session")
```

### List keys matching a pattern
```python
redis_keys(pattern="user:*", count=50)
```

### Work with a hash
```python
redis_hset(key="user:123", field="email", value="alice@example.com")
redis_hgetall(key="user:123")
```

### Work with a list
```python
redis_lpush(key="task_queue", values="task1, task2, task3")
redis_lrange(key="task_queue", start=0, stop=-1)
```

### Publish a message
```python
redis_publish(channel="notifications", message="New order received")
```

### Check TTL
```python
redis_ttl(key="user:123:session")
# Returns: {"key": "user:123:session", "ttl": 3542}
# -1 = no expiry, -2 = key doesn't exist
```

### Get server info
```python
redis_info()
```

## TTL Reference

| TTL Value | Meaning |
|-----------|---------|
| `> 0` | Seconds remaining until expiry |
| `-1` | Key exists with no expiry |
| `-2` | Key does not exist |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "REDIS_URL not set", "help": "Set REDIS_URL (e.g. redis://localhost:6379 or redis://:password@host:6379/0)"}
{"error": "Redis GET failed: Connection refused"}
{"error": "Redis SET failed: ..."}
```