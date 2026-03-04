"""Tests for kafka_tool - Apache Kafka via Confluent REST Proxy."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.kafka_tool.kafka_tool import register_tools

ENV = {
    "KAFKA_REST_URL": "https://kafka.example.com",
    "KAFKA_CLUSTER_ID": "cluster-abc",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestKafkaListTopics:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["kafka_list_topics"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "topic_name": "orders",
                    "partitions_count": 6,
                    "replication_factor": 3,
                    "is_internal": False,
                },
                {
                    "topic_name": "events",
                    "partitions_count": 3,
                    "replication_factor": 3,
                    "is_internal": False,
                },
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_list_topics"]()

        assert result["count"] == 2
        assert result["topics"][0]["name"] == "orders"
        assert result["topics"][0]["partitions_count"] == 6


class TestKafkaGetTopic:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["kafka_get_topic"](topic_name="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "topic_name": "orders",
            "partitions_count": 6,
            "replication_factor": 3,
            "is_internal": False,
            "cluster_id": "cluster-abc",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_get_topic"](topic_name="orders")

        assert result["name"] == "orders"
        assert result["cluster_id"] == "cluster-abc"


class TestKafkaCreateTopic:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["kafka_create_topic"](topic_name="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "topic_name": "new-topic",
            "partitions_count": 3,
            "replication_factor": 3,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_create_topic"](topic_name="new-topic", partitions_count=3)

        assert result["name"] == "new-topic"
        assert result["partitions_count"] == 3


class TestKafkaProduceMessage:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["kafka_produce_message"](topic_name="", value="")
        assert "error" in result

    def test_successful_produce(self, tool_fns):
        data = {
            "topic_name": "orders",
            "partition_id": 0,
            "offset": 42,
            "timestamp": "2024-01-15T12:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.post", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_produce_message"](
                topic_name="orders", value='{"order_id": 123}', key="order-123"
            )

        assert result["topic"] == "orders"
        assert result["offset"] == 42


class TestKafkaListConsumerGroups:
    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "consumer_group_id": "my-group",
                    "is_simple": False,
                    "state": "STABLE",
                    "coordinator": {"related": "broker-1"},
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_list_consumer_groups"]()

        assert result["count"] == 1
        assert result["consumer_groups"][0]["id"] == "my-group"
        assert result["consumer_groups"][0]["state"] == "STABLE"


class TestKafkaGetConsumerGroupLag:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["kafka_get_consumer_group_lag"](consumer_group_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "consumer_group_id": "my-group",
            "max_lag": 100,
            "max_lag_topic_name": "orders",
            "max_lag_partition_id": 2,
            "max_lag_consumer_id": "consumer-1",
            "total_lag": 250,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.kafka_tool.kafka_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["kafka_get_consumer_group_lag"](consumer_group_id="my-group")

        assert result["max_lag"] == 100
        assert result["total_lag"] == 250
        assert result["max_lag_topic"] == "orders"
