"""Tests for Kafka tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.kafka_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


class TestKafkaToolRegistration:
    """Tests for Kafka tool registration."""

    def test_register_tools_creates_all_tools(self, mcp: FastMCP):
        """All Kafka tools are registered."""
        register_tools(mcp)
        tools = list(mcp._tool_manager._tools.keys())
        assert "kafka_produce_message" in tools
        assert "kafka_produce_batch" in tools
        assert "kafka_flush" in tools
        assert "kafka_subscribe" in tools
        assert "kafka_consume_messages" in tools
        assert "kafka_commit_offset" in tools
        assert "kafka_seek" in tools
        assert "kafka_unsubscribe" in tools
        assert "kafka_create_topic" in tools
        assert "kafka_delete_topic" in tools
        assert "kafka_list_topics" in tools
        assert "kafka_describe_topic" in tools
        assert "kafka_list_consumer_groups" in tools
        assert "kafka_describe_consumer_group" in tools
        assert "kafka_delete_consumer_group" in tools
        assert "kafka_get_broker_metadata" in tools
        assert "kafka_get_offsets" in tools


class TestKafkaProduceMessage:
    """Tests for kafka_produce_message tool."""

    def test_produce_message_success(self, monkeypatch):
        """Produce message returns success."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-produce")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.produce.return_value = {"success": True, "topic": "test-topic"}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_produce_message"].fn
                result = fn(topic="test-topic", value={"key": "value"})

        assert result["success"] is True
        assert result["topic"] == "test-topic"

    def test_produce_message_with_key_and_headers(self, monkeypatch):
        """Produce message with key and headers."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-produce-key")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.produce.return_value = {"success": True, "topic": "test-topic"}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_produce_message"].fn
                result = fn(
                    topic="test-topic",
                    value="test message",
                    key="test-key",
                    headers={"source": "test"},
                )

        assert result["success"] is True


class TestKafkaProduceBatch:
    """Tests for kafka_produce_batch tool."""

    def test_produce_batch_success(self, monkeypatch):
        """Produce batch returns success counts."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-batch")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.produce_batch.return_value = {
                    "success": 3,
                    "failed": 0,
                    "total": 3,
                    "errors": None,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_produce_batch"].fn
                result = fn(
                    topic="test-topic",
                    messages=[
                        {"value": "msg1"},
                        {"value": "msg2"},
                        {"value": "msg3"},
                    ],
                )

        assert result["success"] == 3
        assert result["failed"] == 0


class TestKafkaFlush:
    """Tests for kafka_flush tool."""

    def test_flush_success(self, monkeypatch):
        """Flush returns success with remaining count."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-flush")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.flush.return_value = {"success": True, "remaining": 0}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_flush"].fn
                result = fn(timeout=30.0)

        assert result["success"] is True
        assert result["remaining"] == 0


class TestKafkaSubscribe:
    """Tests for kafka_subscribe tool."""

    def test_subscribe_success(self, monkeypatch):
        """Subscribe returns success with topics and group_id."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-subscribe")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.subscribe.return_value = {
                    "success": True,
                    "topics": ["topic1", "topic2"],
                    "group_id": "test-group",
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_subscribe"].fn
                result = fn(topics=["topic1", "topic2"], group_id="test-group")

        assert result["success"] is True
        assert result["topics"] == ["topic1", "topic2"]
        assert result["group_id"] == "test-group"


class TestKafkaConsumeMessages:
    """Tests for kafka_consume_messages tool."""

    def test_consume_messages_success(self, monkeypatch):
        """Consume messages returns message list."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-consume")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.consume_messages.return_value = {
                    "success": True,
                    "messages": [
                        {
                            "topic": "test-topic",
                            "partition": 0,
                            "offset": 1,
                            "key": "key1",
                            "value": "value1",
                            "headers": None,
                        }
                    ],
                    "count": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_consume_messages"].fn
                result = fn(timeout=5.0, max_messages=10)

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["messages"]) == 1

    def test_consume_without_subscribe_returns_error(self, monkeypatch):
        """Consume without subscribe returns error."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-consume-error")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.consume_messages.return_value = {
                    "error": "Not subscribed to any topics. Call kafka_subscribe first."
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_consume_messages"].fn
                result = fn()

        assert "error" in result


class TestKafkaCommitOffset:
    """Tests for kafka_commit_offset tool."""

    def test_commit_offset_success(self, monkeypatch):
        """Commit offset returns success."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-commit")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.commit_offset.return_value = {"success": True}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_commit_offset"].fn
                result = fn()

        assert result["success"] is True


class TestKafkaSeek:
    """Tests for kafka_seek tool."""

    def test_seek_success(self, monkeypatch):
        """Seek returns success with offset details."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-seek")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.seek.return_value = {
                    "success": True,
                    "topic": "test-topic",
                    "partition": 0,
                    "offset": 0,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_seek"].fn
                result = fn(topic="test-topic", partition=0, offset=0)

        assert result["success"] is True


class TestKafkaUnsubscribe:
    """Tests for kafka_unsubscribe tool."""

    def test_unsubscribe_success(self, monkeypatch):
        """Unsubscribe returns success."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-unsub")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.unsubscribe.return_value = {"success": True}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_unsubscribe"].fn
                result = fn()

        assert result["success"] is True


class TestKafkaCreateTopic:
    """Tests for kafka_create_topic tool."""

    def test_create_topic_success(self, monkeypatch):
        """Create topic returns topic details."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-create-topic")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.create_topic.return_value = {
                    "success": True,
                    "topic": "new-topic",
                    "partitions": 3,
                    "replication_factor": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_create_topic"].fn
                result = fn(topic="new-topic", partitions=3, replication_factor=1)

        assert result["success"] is True
        assert result["topic"] == "new-topic"


class TestKafkaDeleteTopic:
    """Tests for kafka_delete_topic tool."""

    def test_delete_topic_success(self, monkeypatch):
        """Delete topic returns success."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-delete-topic")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.delete_topic.return_value = {"success": True, "topic": "old-topic"}
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_delete_topic"].fn
                result = fn(topic="old-topic")

        assert result["success"] is True


class TestKafkaListTopics:
    """Tests for kafka_list_topics tool."""

    def test_list_topics_success(self, monkeypatch):
        """List topics returns topic list."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-list-topics")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.list_topics.return_value = {
                    "success": True,
                    "topics": [
                        {"name": "topic1", "partitions": 3, "error": None},
                        {"name": "topic2", "partitions": 1, "error": None},
                    ],
                    "count": 2,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_list_topics"].fn
                result = fn()

        assert result["success"] is True
        assert result["count"] == 2


class TestKafkaDescribeTopic:
    """Tests for kafka_describe_topic tool."""

    def test_describe_topic_success(self, monkeypatch):
        """Describe topic returns partition details."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-describe-topic")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.describe_topic.return_value = {
                    "success": True,
                    "topic": "test-topic",
                    "partitions": [
                        {"id": 0, "leader": 1, "replicas": [1], "isrs": [1]},
                    ],
                    "partition_count": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_describe_topic"].fn
                result = fn(topic="test-topic")

        assert result["success"] is True
        assert result["partition_count"] == 1


class TestKafkaListConsumerGroups:
    """Tests for kafka_list_consumer_groups tool."""

    def test_list_consumer_groups_success(self, monkeypatch):
        """List consumer groups returns group list."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-list-groups")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.list_consumer_groups.return_value = {
                    "success": True,
                    "groups": [
                        {"id": "group1", "state": "Stable", "is_simple": True, "members": 2},
                    ],
                    "count": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_list_consumer_groups"].fn
                result = fn()

        assert result["success"] is True
        assert result["count"] == 1


class TestKafkaDescribeConsumerGroup:
    """Tests for kafka_describe_consumer_group tool."""

    def test_describe_consumer_group_success(self, monkeypatch):
        """Describe consumer group returns group details."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-describe-group")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.describe_consumer_group.return_value = {
                    "success": True,
                    "group_id": "test-group",
                    "state": "Stable",
                    "is_simple": True,
                    "members": [
                        {
                            "member_id": "member1",
                            "client_id": "client-1",
                            "client_host": "/127.0.0.1",
                        },
                    ],
                    "member_count": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_describe_consumer_group"].fn
                result = fn(group_id="test-group")

        assert result["success"] is True
        assert result["member_count"] == 1


class TestKafkaDeleteConsumerGroup:
    """Tests for kafka_delete_consumer_group tool."""

    def test_delete_consumer_group_success(self, monkeypatch):
        """Delete consumer group returns success."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-delete-group")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.delete_consumer_group.return_value = {
                    "success": True,
                    "group_id": "old-group",
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_delete_consumer_group"].fn
                result = fn(group_id="old-group")

        assert result["success"] is True


class TestKafkaGetBrokerMetadata:
    """Tests for kafka_get_broker_metadata tool."""

    def test_get_broker_metadata_success(self, monkeypatch):
        """Get broker metadata returns cluster info."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-broker-meta")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.get_broker_metadata.return_value = {
                    "success": True,
                    "cluster_id": "test-cluster",
                    "controller_id": 1,
                    "brokers": [
                        {"id": 1, "host": "localhost", "port": 9092},
                    ],
                    "broker_count": 1,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_get_broker_metadata"].fn
                result = fn()

        assert result["success"] is True
        assert result["broker_count"] == 1


class TestKafkaGetOffsets:
    """Tests for kafka_get_offsets tool."""

    def test_get_offsets_success(self, monkeypatch):
        """Get offsets returns earliest and latest offsets."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-offsets")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", True):
            with patch("aden_tools.tools.kafka_tool.kafka_tool._KafkaClient") as MockClient:
                mock_instance = MagicMock()
                mock_instance.get_offsets.return_value = {
                    "success": True,
                    "topic": "test-topic",
                    "partition": 0,
                    "earliest_offset": 0,
                    "latest_offset": 100,
                    "message_count": 100,
                }
                MockClient.return_value = mock_instance

                register_tools(mcp)
                fn = mcp._tool_manager._tools["kafka_get_offsets"].fn
                result = fn(topic="test-topic", partition=0)

        assert result["success"] is True
        assert result["message_count"] == 100


class TestKafkaNotInstalled:
    """Tests for when confluent-kafka is not installed."""

    def test_produce_without_kafka_library(self, monkeypatch):
        """Returns helpful error when confluent-kafka is not installed."""
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        mcp = FastMCP("test-no-kafka")
        with patch("aden_tools.tools.kafka_tool.kafka_tool.KAFKA_AVAILABLE", False):
            register_tools(mcp)
            fn = mcp._tool_manager._tools["kafka_produce_message"].fn
            result = fn(topic="test-topic", value="test")

        assert "error" in result
        assert "confluent-kafka is not installed" in result["error"]
        assert "help" in result
