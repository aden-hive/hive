"""
Kafka Tool - Produce and consume messages from Apache Kafka topics.

Supports:
- Producer operations: publish messages to topics
- Consumer operations: subscribe and consume messages
- Topic management: create, delete, list topics
- Consumer group management: list, describe, delete groups
- Cluster information: broker metadata, offsets

Uses confluent-kafka-python for high-performance Kafka client operations.

API Reference: https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

try:
    from confluent_kafka import (
        AdminClient,
        Consumer,
        KafkaError,
        KafkaException,
        Producer,
        TopicPartition,
    )

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False


def _get_config(credentials: CredentialStoreAdapter | None = None) -> dict[str, Any]:
    """Build Kafka configuration from credentials or environment."""
    config: dict[str, Any] = {}

    if credentials is not None:
        bootstrap_servers = credentials.get("kafka_bootstrap_servers")
        sasl_username = credentials.get("kafka_sasl_username")
        sasl_password = credentials.get("kafka_sasl_password")
        ssl_ca_location = credentials.get("kafka_ssl_ca_location")
        security_protocol = credentials.get("kafka_security_protocol")
    else:
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        sasl_username = os.getenv("KAFKA_SASL_USERNAME")
        sasl_password = os.getenv("KAFKA_SASL_PASSWORD")
        ssl_ca_location = os.getenv("KAFKA_SSL_CA_LOCATION")
        security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL")

    if bootstrap_servers:
        config["bootstrap.servers"] = bootstrap_servers
    else:
        config["bootstrap.servers"] = "localhost:9092"

    if security_protocol:
        config["security.protocol"] = security_protocol

    if sasl_username and sasl_password:
        config["sasl.mechanisms"] = "PLAIN"
        config["sasl.username"] = sasl_username
        config["sasl.password"] = sasl_password

    if ssl_ca_location:
        config["ssl.ca.location"] = ssl_ca_location

    return config


def _serialize_value(
    value: Any, headers: dict[str, str] | None = None
) -> tuple[bytes | None, list[tuple[str, bytes]]]:
    """Serialize a value to bytes for Kafka."""
    if value is None:
        return None, []

    if isinstance(value, bytes):
        serialized = value
    elif isinstance(value, str):
        serialized = value.encode("utf-8")
    else:
        serialized = json.dumps(value).encode("utf-8")

    serialized_headers = []
    if headers:
        for k, v in headers.items():
            serialized_headers.append((k, v.encode("utf-8") if isinstance(v, str) else v))

    return serialized, serialized_headers


def _deserialize_message(msg: Any) -> dict[str, Any]:
    """Deserialize a Kafka message to a dictionary."""
    result = {
        "topic": msg.topic(),
        "partition": msg.partition(),
        "offset": msg.offset(),
        "key": msg.key().decode("utf-8") if msg.key() else None,
        "timestamp": msg.timestamp()[1] if msg.timestamp()[0] else None,
        "timestamp_type": msg.timestamp()[0],
    }

    value = msg.value()
    if value:
        try:
            result["value"] = json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            result["value"] = value.decode("utf-8", errors="replace")
    else:
        result["value"] = None

    headers = msg.headers()
    if headers:
        result["headers"] = {k: v.decode("utf-8") if v else None for k, v in headers}
    else:
        result["headers"] = None

    return result


class _KafkaClient:
    """Internal client wrapping Kafka operations."""

    def __init__(self, config: dict[str, Any]):
        if not KAFKA_AVAILABLE:
            raise ImportError(
                "confluent-kafka is not installed. Install it with: pip install confluent-kafka"
            )
        self._config = config
        self._producer: Producer | None = None
        self._consumer: Consumer | None = None
        self._admin: AdminClient | None = None

    def _get_producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer(self._config)
        return self._producer

    def _get_admin(self) -> AdminClient:
        if self._admin is None:
            self._admin = AdminClient(self._config)
        return self._admin

    def produce(
        self,
        topic: str,
        value: Any,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        partition: int | None = None,
    ) -> dict[str, Any]:
        """Produce a single message to a topic."""
        producer = self._get_producer()
        serialized_value, serialized_headers = _serialize_value(value, headers)

        try:
            producer.produce(
                topic,
                value=serialized_value,
                key=key.encode("utf-8") if key else None,
                headers=serialized_headers if serialized_headers else None,
                partition=partition if partition is not None else -1,
            )
            return {"success": True, "topic": topic}
        except KafkaException as e:
            return {"error": f"Failed to produce message: {e}"}
        except BufferError as e:
            return {"error": f"Producer queue full: {e}"}

    def produce_batch(
        self,
        topic: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Produce multiple messages to a topic."""
        producer = self._get_producer()
        success_count = 0
        errors = []

        for i, msg in enumerate(messages):
            value = msg.get("value")
            key = msg.get("key")
            headers = msg.get("headers")
            partition = msg.get("partition")

            serialized_value, serialized_headers = _serialize_value(value, headers)

            try:
                producer.produce(
                    topic,
                    value=serialized_value,
                    key=key.encode("utf-8") if key else None,
                    headers=serialized_headers if serialized_headers else None,
                    partition=partition if partition is not None else -1,
                )
                success_count += 1
            except (KafkaException, BufferError) as e:
                errors.append({"index": i, "error": str(e)})

        return {
            "success": success_count,
            "failed": len(errors),
            "total": len(messages),
            "errors": errors if errors else None,
        }

    def flush(self, timeout: float = 30.0) -> dict[str, Any]:
        """Wait for all messages to be delivered."""
        producer = self._get_producer()
        try:
            remaining = producer.flush(timeout)
            return {"success": True, "remaining": remaining}
        except KafkaException as e:
            return {"error": f"Flush failed: {e}"}

    def subscribe(
        self,
        topics: list[str],
        group_id: str,
        auto_offset_reset: str = "latest",
    ) -> dict[str, Any]:
        """Subscribe to one or more topics."""
        if self._consumer is not None:
            self._consumer.close()

        consumer_config = {
            **self._config,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": False,
        }

        try:
            self._consumer = Consumer(consumer_config)
            self._consumer.subscribe(topics)
            return {"success": True, "topics": topics, "group_id": group_id}
        except KafkaException as e:
            return {"error": f"Failed to subscribe: {e}"}

    def consume_messages(
        self,
        timeout: float = 5.0,
        max_messages: int = 10,
    ) -> dict[str, Any]:
        """Poll and retrieve messages from subscribed topics."""
        if self._consumer is None:
            return {"error": "Not subscribed to any topics. Call kafka_subscribe first."}

        messages = []
        elapsed = 0.0
        import time

        start_time = time.time()

        while len(messages) < max_messages and elapsed < timeout:
            msg = self._consumer.poll(1.0)
            if msg is None:
                elapsed = time.time() - start_time
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    elapsed = time.time() - start_time
                    continue
                return {"error": f"Consumer error: {msg.error()}"}

            messages.append(_deserialize_message(msg))
            elapsed = time.time() - start_time

        return {
            "success": True,
            "messages": messages,
            "count": len(messages),
        }

    def commit_offset(
        self,
        topic: str | None = None,
        partition: int | None = None,
        offset: int | None = None,
        asynchronous: bool = True,
    ) -> dict[str, Any]:
        """Commit consumer position."""
        if self._consumer is None:
            return {"error": "Not subscribed to any topics."}

        try:
            if topic is not None and partition is not None and offset is not None:
                tp = TopicPartition(topic, partition, offset)
                self._consumer.commit(offsets=[tp], asynchronous=asynchronous)
            else:
                self._consumer.commit(asynchronous=asynchronous)
            return {"success": True}
        except KafkaException as e:
            return {"error": f"Failed to commit offset: {e}"}

    def seek(
        self,
        topic: str,
        partition: int,
        offset: int,
    ) -> dict[str, Any]:
        """Reset consumer position to a specific offset."""
        if self._consumer is None:
            return {"error": "Not subscribed to any topics."}

        try:
            tp = TopicPartition(topic, partition, offset)
            self._consumer.seek(tp)
            return {"success": True, "topic": topic, "partition": partition, "offset": offset}
        except KafkaException as e:
            return {"error": f"Failed to seek: {e}"}

    def unsubscribe(self) -> dict[str, Any]:
        """Stop consuming and close the consumer."""
        if self._consumer is None:
            return {"success": True, "message": "No active consumer"}

        try:
            self._consumer.unsubscribe()
            self._consumer.close()
            self._consumer = None
            return {"success": True}
        except KafkaException as e:
            return {"error": f"Failed to unsubscribe: {e}"}

    def create_topic(
        self,
        topic: str,
        num_partitions: int = 1,
        replication_factor: int = 1,
        config: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a new topic."""
        from confluent_kafka.admin import NewTopic

        admin = self._get_admin()

        new_topic = NewTopic(
            topic,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
        )
        if config:
            new_topic.set_config_dict(config)

        try:
            fs = admin.create_topics([new_topic])
            for _t, f in fs.items():
                f.result()
            return {
                "success": True,
                "topic": topic,
                "partitions": num_partitions,
                "replication_factor": replication_factor,
            }
        except KafkaException as e:
            return {"error": f"Failed to create topic: {e}"}
        except Exception as e:
            return {"error": f"Failed to create topic: {str(e)}"}

    def delete_topic(self, topic: str) -> dict[str, Any]:
        """Delete a topic."""
        admin = self._get_admin()

        try:
            fs = admin.delete_topics([topic])
            for _t, f in fs.items():
                f.result()
            return {"success": True, "topic": topic}
        except KafkaException as e:
            return {"error": f"Failed to delete topic: {e}"}
        except Exception as e:
            return {"error": f"Failed to delete topic: {str(e)}"}

    def list_topics(self, topic: str | None = None) -> dict[str, Any]:
        """List all topics or get metadata for a specific topic."""
        admin = self._get_admin()

        try:
            metadata = admin.list_topics(topic=topic, timeout=10)
            topics = []
            for t_name, t_metadata in metadata.topics.items():
                topics.append(
                    {
                        "name": t_name,
                        "partitions": len(t_metadata.partitions),
                        "error": str(t_metadata.error) if t_metadata.error else None,
                    }
                )
            return {"success": True, "topics": topics, "count": len(topics)}
        except KafkaException as e:
            return {"error": f"Failed to list topics: {e}"}

    def describe_topic(self, topic: str) -> dict[str, Any]:
        """Get detailed metadata for a topic."""
        admin = self._get_admin()

        try:
            metadata = admin.list_topics(topic=topic, timeout=10)

            if topic not in metadata.topics:
                return {"error": f"Topic '{topic}' not found"}

            t_metadata = metadata.topics[topic]
            partitions = []
            for p_id, p_metadata in t_metadata.partitions():
                partitions.append(
                    {
                        "id": p_id,
                        "leader": p_metadata.leader,
                        "replicas": p_metadata.replicas,
                        "isrs": p_metadata.isrs,
                    }
                )

            return {
                "success": True,
                "topic": topic,
                "partitions": partitions,
                "partition_count": len(partitions),
            }
        except KafkaException as e:
            return {"error": f"Failed to describe topic: {e}"}

    def list_consumer_groups(self) -> dict[str, Any]:
        """List all consumer groups."""
        admin = self._get_admin()

        try:
            groups = admin.list_groups(timeout=10)
            result = []
            for g in groups:
                if not g.error:
                    result.append(
                        {
                            "id": g.id,
                            "state": g.state,
                            "is_simple": g.is_simple,
                            "members": len(g.members) if hasattr(g, "members") else 0,
                        }
                    )
            return {"success": True, "groups": result, "count": len(result)}
        except KafkaException as e:
            return {"error": f"Failed to list consumer groups: {e}"}

    def describe_consumer_group(self, group_id: str) -> dict[str, Any]:
        """Get details about a consumer group including lag."""
        admin = self._get_admin()

        try:
            groups = admin.list_groups(group_id, timeout=10)

            if not groups:
                return {"error": f"Consumer group '{group_id}' not found"}

            g = groups[0]
            members = []
            if hasattr(g, "members"):
                for m in g.members:
                    members.append(
                        {
                            "member_id": m.id,
                            "client_id": m.client_id,
                            "client_host": m.client_host,
                        }
                    )

            return {
                "success": True,
                "group_id": g.id,
                "state": g.state,
                "is_simple": g.is_simple,
                "members": members,
                "member_count": len(members),
            }
        except KafkaException as e:
            return {"error": f"Failed to describe consumer group: {e}"}

    def delete_consumer_group(self, group_id: str) -> dict[str, Any]:
        """Delete a consumer group."""
        admin = self._get_admin()

        try:
            fs = admin.delete_groups([group_id])
            for _g, f in fs.items():
                f.result()
            return {"success": True, "group_id": group_id}
        except KafkaException as e:
            return {"error": f"Failed to delete consumer group: {e}"}
        except Exception as e:
            return {"error": f"Failed to delete consumer group: {str(e)}"}

    def get_broker_metadata(self) -> dict[str, Any]:
        """Get broker and cluster information."""
        admin = self._get_admin()

        try:
            metadata = admin.list_topics(timeout=10)
            brokers = []
            for b_id, b_metadata in metadata.brokers.items():
                brokers.append(
                    {
                        "id": b_id,
                        "host": b_metadata.host,
                        "port": b_metadata.port,
                    }
                )
            return {
                "success": True,
                "cluster_id": metadata.cluster_id,
                "controller_id": metadata.controller_id,
                "brokers": brokers,
                "broker_count": len(brokers),
            }
        except KafkaException as e:
            return {"error": f"Failed to get broker metadata: {e}"}

    def get_offsets(
        self,
        topic: str,
        partition: int = 0,
    ) -> dict[str, Any]:
        """Get earliest and latest offsets for a topic partition."""
        admin = self._get_admin()

        try:
            metadata = admin.list_topics(topic=topic, timeout=10)

            if topic not in metadata.topics:
                return {"error": f"Topic '{topic}' not found"}

            consumer_config = {**self._config, "group.id": "offset-query-temp"}
            consumer = Consumer(consumer_config)

            try:
                low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition))
                return {
                    "success": True,
                    "topic": topic,
                    "partition": partition,
                    "earliest_offset": low,
                    "latest_offset": high,
                    "message_count": high - low,
                }
            finally:
                consumer.close()
        except KafkaException as e:
            return {"error": f"Failed to get offsets: {e}"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Kafka tools with the MCP server."""

    def _get_client() -> _KafkaClient | dict[str, str]:
        """Get a Kafka client, or return an error dict if not available."""
        if not KAFKA_AVAILABLE:
            return {
                "error": "confluent-kafka is not installed",
                "help": "Install with: pip install confluent-kafka",
            }
        config = _get_config(credentials)
        return _KafkaClient(config)

    _client_instance: _KafkaClient | None = None

    def _get_or_create_client() -> _KafkaClient | dict[str, str]:
        nonlocal _client_instance
        if not KAFKA_AVAILABLE:
            return {
                "error": "confluent-kafka is not installed",
                "help": "Install with: pip install confluent-kafka",
            }
        if _client_instance is None:
            config = _get_config(credentials)
            _client_instance = _KafkaClient(config)
        return _client_instance

    @mcp.tool()
    def kafka_produce_message(
        topic: str,
        value: str | dict | None,
        key: str | None = None,
        headers: dict | None = None,
        partition: int | None = None,
    ) -> dict:
        """
        Publish a message to a Kafka topic.

        Args:
            topic: Topic name to publish to
            value: Message value (string, dict for JSON, or None for tombstone)
            key: Optional message key for partitioning
            headers: Optional headers as key-value pairs
            partition: Optional specific partition (default: auto-select)

        Returns:
            Dict with success status or error
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.produce(topic, value, key, headers, partition)

    @mcp.tool()
    def kafka_produce_batch(
        topic: str,
        messages: list[dict],
    ) -> dict:
        """
        Publish multiple messages to a Kafka topic efficiently.

        Args:
            topic: Topic name to publish to
            messages: List of message dicts, each with optional keys: value, key, headers, partition

        Returns:
            Dict with success/failure counts and any errors
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.produce_batch(topic, messages)

    @mcp.tool()
    def kafka_flush(timeout: float = 30.0) -> dict:
        """
        Wait for all buffered messages to be delivered.

        Args:
            timeout: Maximum seconds to wait (default: 30)

        Returns:
            Dict with success status and remaining unflushed messages
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.flush(timeout)

    @mcp.tool()
    def kafka_subscribe(
        topics: list[str],
        group_id: str,
        auto_offset_reset: str = "latest",
    ) -> dict:
        """
        Subscribe to one or more Kafka topics.

        Args:
            topics: List of topic names to subscribe to
            group_id: Consumer group ID for coordinated consumption
            auto_offset_reset: Where to start if no committed offset ('earliest' or 'latest')

        Returns:
            Dict with subscription status
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.subscribe(topics, group_id, auto_offset_reset)

    @mcp.tool()
    def kafka_consume_messages(
        timeout: float = 5.0,
        max_messages: int = 10,
    ) -> dict:
        """
        Poll and retrieve messages from subscribed topics.

        Args:
            timeout: Maximum seconds to wait for messages (default: 5)
            max_messages: Maximum messages to return (default: 10)

        Returns:
            Dict with list of messages, each with topic, partition, offset, key, value, headers
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.consume_messages(timeout, max_messages)

    @mcp.tool()
    def kafka_commit_offset(
        topic: str | None = None,
        partition: int | None = None,
        offset: int | None = None,
        asynchronous: bool = True,
    ) -> dict:
        """
        Commit consumer position (offset).

        Args:
            topic: Optional topic for specific offset commit
            partition: Optional partition (required if topic is specified)
            offset: Optional offset (required if topic is specified)
            asynchronous: If True, return immediately (default: True)

        Returns:
            Dict with success status
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.commit_offset(topic, partition, offset, asynchronous)

    @mcp.tool()
    def kafka_seek(
        topic: str,
        partition: int,
        offset: int,
    ) -> dict:
        """
        Reset consumer position to a specific offset.

        Args:
            topic: Topic name
            partition: Partition number
            offset: Offset to seek to (use 0 for beginning, -1 for end)

        Returns:
            Dict with success status
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.seek(topic, partition, offset)

    @mcp.tool()
    def kafka_unsubscribe() -> dict:
        """
        Stop consuming messages and leave the consumer group.

        Returns:
            Dict with success status
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.unsubscribe()

    @mcp.tool()
    def kafka_create_topic(
        topic: str,
        partitions: int = 1,
        replication_factor: int = 1,
        config: dict | None = None,
    ) -> dict:
        """
        Create a new Kafka topic.

        Args:
            topic: Topic name to create
            partitions: Number of partitions (default: 1)
            replication_factor: Replication factor (default: 1)
            config: Optional topic configuration (e.g., retention.ms, cleanup.policy)

        Returns:
            Dict with created topic details or error
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.create_topic(topic, partitions, replication_factor, config)

    @mcp.tool()
    def kafka_delete_topic(topic: str) -> dict:
        """
        Delete a Kafka topic.

        Args:
            topic: Topic name to delete

        Returns:
            Dict with success status or error
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.delete_topic(topic)

    @mcp.tool()
    def kafka_list_topics(topic: str | None = None) -> dict:
        """
        List all Kafka topics or get metadata for a specific topic.

        Args:
            topic: Optional topic name to filter

        Returns:
            Dict with list of topics and their partition counts
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.list_topics(topic)

    @mcp.tool()
    def kafka_describe_topic(topic: str) -> dict:
        """
        Get detailed metadata for a Kafka topic.

        Args:
            topic: Topic name to describe

        Returns:
            Dict with partition details, leaders, replicas, and ISRs
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.describe_topic(topic)

    @mcp.tool()
    def kafka_list_consumer_groups() -> dict:
        """
        List all consumer groups in the Kafka cluster.

        Returns:
            Dict with list of consumer groups and their states
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.list_consumer_groups()

    @mcp.tool()
    def kafka_describe_consumer_group(group_id: str) -> dict:
        """
        Get details about a consumer group including members.

        Args:
            group_id: Consumer group ID to describe

        Returns:
            Dict with group state, members, and their details
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.describe_consumer_group(group_id)

    @mcp.tool()
    def kafka_delete_consumer_group(group_id: str) -> dict:
        """
        Delete a consumer group.

        Args:
            group_id: Consumer group ID to delete

        Returns:
            Dict with success status or error
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.delete_consumer_group(group_id)

    @mcp.tool()
    def kafka_get_broker_metadata() -> dict:
        """
        Get broker and cluster information.

        Returns:
            Dict with cluster ID, controller, and list of brokers
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.get_broker_metadata()

    @mcp.tool()
    def kafka_get_offsets(
        topic: str,
        partition: int = 0,
    ) -> dict:
        """
        Get earliest and latest offsets for a topic partition.

        Args:
            topic: Topic name
            partition: Partition number (default: 0)

        Returns:
            Dict with earliest/latest offsets and message count
        """
        client = _get_or_create_client()
        if isinstance(client, dict):
            return client
        return client.get_offsets(topic, partition)
