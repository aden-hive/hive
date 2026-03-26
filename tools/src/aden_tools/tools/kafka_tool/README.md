# Kafka Tool

Manage Apache Kafka topics, produce messages, and monitor consumer groups via the Confluent REST Proxy v3.

## Supported Actions

- **kafka_list_topics** – List all topics in the cluster with partition and replication metadata
- **kafka_get_topic** – Get detailed metadata for a specific topic
- **kafka_create_topic** – Create a new topic with configurable partitions and replication factor
- **kafka_produce_message** – Produce a message (JSON, STRING, or BINARY) to a topic with optional key
- **kafka_list_consumer_groups** – List all consumer groups and their states
- **kafka_get_consumer_group_lag** – Get lag summary for a consumer group (max lag, total lag, lagging partitions)

## Setup

1. Deploy or connect to a [Confluent REST Proxy](https://docs.confluent.io/platform/current/kafka-rest/index.html) instance.

2. Set the required environment variables:
   ```bash
   export KAFKA_REST_URL=http://localhost:8082   # REST Proxy URL
   export KAFKA_CLUSTER_ID=your-cluster-id       # Kafka cluster ID
   ```

3. For authenticated clusters, also set:
   ```bash
   export KAFKA_API_KEY=your-api-key
   export KAFKA_API_SECRET=your-api-secret
   ```

## Use Case

Example: "Monitor consumer group lag across all topics and alert when any group falls behind by more than 10,000 messages."
