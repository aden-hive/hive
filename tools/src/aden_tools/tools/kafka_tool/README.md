# Kafka Tool

Manage Apache Kafka topics, produce messages, and monitor consumer groups via the Confluent Kafka REST API.

## Tools

| Tool | Description |
|------|-------------|
| `kafka_list_topics` | List all topics in the Kafka cluster |
| `kafka_get_topic` | Get details and configuration of a topic |
| `kafka_create_topic` | Create a new topic with partition and replication settings |
| `kafka_produce_message` | Produce a message to a topic |
| `kafka_list_consumer_groups` | List all consumer groups |
| `kafka_get_consumer_group_lag` | Get consumer lag for a group |

## Setup

Set the following environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `KAFKA_REST_URL` | Yes | Confluent Kafka REST Proxy URL |
| `KAFKA_CLUSTER_ID` | Yes | Kafka cluster ID |
| `KAFKA_API_KEY` | No | API key (for authenticated clusters) |
| `KAFKA_API_SECRET` | No | API secret (for authenticated clusters) |

Get credentials at: [Confluent Cloud](https://confluent.cloud/)

## Usage Examples

### List topics
```python
kafka_list_topics()
```

### Create a topic
```python
kafka_create_topic(topic_name="events", partitions_count=3, replication_factor=3)
```

### Produce a message
```python
kafka_produce_message(topic_name="events", key="user-123", value='{"action": "login"}')
```

### Check consumer lag
```python
kafka_get_consumer_group_lag(consumer_group_id="my-consumer-group")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "KAFKA_REST_URL is required", "help": "Set KAFKA_REST_URL environment variable"}
{"error": "KAFKA_CLUSTER_ID is required", "help": "Set KAFKA_CLUSTER_ID environment variable"}
{"error": "Request timed out"}
```
