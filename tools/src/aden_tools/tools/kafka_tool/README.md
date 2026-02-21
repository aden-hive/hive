# Apache Kafka Tool

Produce and consume messages from Apache Kafka topics for distributed event streaming and message processing.

## Features

- **Producer Operations**: Publish single or batch messages to topics
- **Consumer Operations**: Subscribe, consume, commit offsets, seek
- **Topic Management**: Create, delete, list, and describe topics
- **Consumer Group Management**: List, describe, and delete consumer groups
- **Cluster Information**: Get broker metadata and topic offsets

## Configuration

Set environment variables for Kafka connection:

```bash
# Required
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Optional - SASL authentication
KAFKA_SASL_USERNAME=your-username
KAFKA_SASL_PASSWORD=your-password
KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT  # or SASL_SSL, SSL

# Optional - SSL/TLS
KAFKA_SSL_CA_LOCATION=/path/to/ca.pem
```

## Tools

### Producer Operations

| Tool | Description |
|------|-------------|
| `kafka_produce_message` | Publish a single message to a topic |
| `kafka_produce_batch` | Publish multiple messages efficiently |
| `kafka_flush` | Wait for all buffered messages to be delivered |

### Consumer Operations

| Tool | Description |
|------|-------------|
| `kafka_subscribe` | Subscribe to one or more topics |
| `kafka_consume_messages` | Poll and retrieve messages |
| `kafka_commit_offset` | Commit consumer position |
| `kafka_seek` | Reset consumer position |
| `kafka_unsubscribe` | Stop consuming and leave group |

### Topic Management

| Tool | Description |
|------|-------------|
| `kafka_create_topic` | Create a new topic |
| `kafka_delete_topic` | Delete a topic |
| `kafka_list_topics` | List all topics |
| `kafka_describe_topic` | Get topic metadata |

### Consumer Group Management

| Tool | Description |
|------|-------------|
| `kafka_list_consumer_groups` | List all consumer groups |
| `kafka_describe_consumer_group` | Get group details |
| `kafka_delete_consumer_group` | Delete a consumer group |

### Cluster Information

| Tool | Description |
|------|-------------|
| `kafka_get_broker_metadata` | Get broker and cluster info |
| `kafka_get_offsets` | Get earliest/latest offsets |

## Usage Examples

### Producing Messages

```python
# Single message
kafka_produce_message(
    topic="orders",
    value={"order_id": 123, "customer": "Alice"},
    key="order-123",
    headers={"source": "web-app"}
)

# Batch production
kafka_produce_batch(
    topic="events",
    messages=[
        {"value": {"event": "click"}, "key": "user-1"},
        {"value": {"event": "purchase"}, "key": "user-2"},
    ]
)

# Ensure delivery
kafka_flush(timeout=30.0)
```

### Consuming Messages

```python
# Subscribe to topics
kafka_subscribe(
    topics=["orders", "events"],
    group_id="order-processor",
    auto_offset_reset="earliest"
)

# Consume messages
result = kafka_consume_messages(timeout=5.0, max_messages=10)
for msg in result["messages"]:
    print(f"Received: {msg['value']} from {msg['topic']}")
    kafka_commit_offset()  # Commit after processing

# Clean up
kafka_unsubscribe()
```

### Topic Management

```python
# Create topic
kafka_create_topic(
    topic="analytics",
    partitions=3,
    replication_factor=1,
    config={"retention.ms": "86400000"}
)

# List topics
kafka_list_topics()

# Describe topic
kafka_describe_topic(topic="analytics")

# Delete topic
kafka_delete_topic(topic="old-topic")
```

## Error Handling

All tools return a dict with either:
- `success: True` and relevant data
- `error: "error message"` with description

## Dependencies

- `confluent-kafka` - Official Python client for Apache Kafka

Install with:
```bash
pip install confluent-kafka
```

## Security

- Supports SASL/PLAIN authentication
- SSL/TLS encryption in transit
- Credentials stored via Hive credential system
