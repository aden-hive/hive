# Infrastructure Guide

This guide covers Hive's production-grade infrastructure modules for observability, performance, and reliability.

## Modules Overview

| Module          | Path                     | Purpose                           |
| --------------- | ------------------------ | --------------------------------- |
| Telemetry       | `framework/telemetry.py` | OpenTelemetry tracing and metrics |
| Cache           | `framework/cache.py`     | Multi-tier LRU cache with TTL     |
| Rate Limiting   | `framework/ratelimit.py` | Token bucket rate limiting        |
| Health          | `framework/health.py`    | Health check system               |
| Logging         | `framework/logging.py`   | Structured JSON logging           |
| Connection Pool | `framework/llm/pool.py`  | Async connection pooling          |

## Telemetry

OpenTelemetry integration for distributed tracing and metrics.

```python
from framework.telemetry import get_tracer, get_meter

# Create tracer
tracer = get_tracer("my.service")

# Create span for operation
with tracer.start_as_current_span("operation") as span:
    span.set_attribute("key", "value")
    # Your code here

# Metrics
meter = get_meter("my.service")
counter = meter.create_counter("requests.count")
counter.add(1, {"endpoint": "/api"})
```

### Configuration

Set environment variables for tracing backends:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=hive
```

## Caching

Multi-tier LRU cache for LLM responses and expensive computations.

```python
from framework.cache import LRUCache, get_cache

# Get global cache
cache = get_cache()

# Store with TTL (seconds)
await cache.set("key", value, ttl=3600)

# Retrieve
result = await cache.get("key")
if result:
    print(result.value)

# Custom cache
my_cache = LRUCache(max_size=500)
```

### Features

- Async-safe operations
- Automatic TTL expiration
- LRU eviction when full
- Optional persistence

## Rate Limiting

Token bucket rate limiting for API calls.

```python
from framework.ratelimit import TokenBucket, get_limiter

# Get limiter for a resource
limiter = get_limiter("openai-api")

# Check if request allowed
if await limiter.acquire():
    # Make request
    pass
else:
    # Rate limited
    pass

# Custom bucket
bucket = TokenBucket(
    rate=10,         # 10 tokens per second
    capacity=100,    # Max burst
)
```

## Health Checks

Multi-component health monitoring.

```python
from framework.health import HealthChecker, get_health, HealthStatus

# Get global health checker
health = get_health()

# Register custom check
@health.register("database")
async def check_db():
    # Check database connection
    return HealthStatus.HEALTHY

# Run all checks
report = await health.check_all()
print(report.status)  # HEALTHY, DEGRADED, or UNHEALTHY
```

## Structured Logging

JSON-formatted logs with correlation IDs.

```python
from framework.logging import get_logger, StructuredLogger

# Get logger
logger = get_logger(__name__)

# Structured log
logger.info("Request received", request_id="abc123", user="john")

# Output: {"timestamp": "...", "level": "INFO", "message": "Request received", "request_id": "abc123", "user": "john"}
```

## Connection Pooling

Async connection pool for LLM providers.

```python
from framework.llm.pool import ConnectionPool

pool = ConnectionPool(
    factory=create_connection,
    max_size=10,
    max_idle_time=300,
)

# Acquire connection
async with pool.acquire() as conn:
    response = await conn.complete(...)
```

## Integration with Core

These modules are automatically integrated into the core framework:

- **Executor** - Traces node execution, records metrics
- **LLM Provider** - Caches responses, traces API calls
- **Orchestrator** - Health checks, structured logging

No additional configuration required for basic usage.
