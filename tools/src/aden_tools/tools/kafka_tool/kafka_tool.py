"""Apache Kafka integration via Confluent REST Proxy v3.

Provides topic management, message producing, and consumer group monitoring.
Requires KAFKA_REST_URL and optionally KAFKA_API_KEY + KAFKA_API_SECRET.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _get_config() -> tuple[str, str, dict] | dict:
    """Return (base_url, cluster_id, headers) or error dict."""
    rest_url = os.getenv("KAFKA_REST_URL", "").rstrip("/")
    cluster_id = os.getenv("KAFKA_CLUSTER_ID", "")
    if not rest_url:
        return {"error": "KAFKA_REST_URL is required"}
    if not cluster_id:
        return {"error": "KAFKA_CLUSTER_ID is required"}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = os.getenv("KAFKA_API_KEY", "")
    api_secret = os.getenv("KAFKA_API_SECRET", "")
    if api_key and api_secret:
        creds = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    base_url = f"{rest_url}/v3/clusters/{cluster_id}"
    return base_url, cluster_id, headers


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    resp = httpx.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(url: str, headers: dict, payload: dict) -> dict:
    """Send a POST request."""
    resp = httpx.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _delete(url: str, headers: dict) -> dict:
    """Send a DELETE request."""
    resp = httpx.delete(url, headers=headers, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    if resp.status_code == 204:
        return {"result": "deleted"}
    return resp.json()


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Kafka tools."""

    @mcp.tool()
    def kafka_list_topics() -> dict:
        """List all Kafka topics in the cluster."""
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg

        data = _get(f"{base_url}/topics", headers)
        if "error" in data:
            return data

        topics = data.get("data", [])
        return {
            "count": len(topics),
            "topics": [
                {
                    "name": t.get("topic_name"),
                    "partitions_count": t.get("partitions_count"),
                    "replication_factor": t.get("replication_factor"),
                    "is_internal": t.get("is_internal"),
                }
                for t in topics
            ],
        }

    @mcp.tool()
    def kafka_get_topic(topic_name: str) -> dict:
        """Get metadata for a specific Kafka topic.

        Args:
            topic_name: The topic name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg
        if not topic_name:
            return {"error": "topic_name is required"}

        data = _get(f"{base_url}/topics/{topic_name}", headers)
        if "error" in data:
            return data

        return {
            "name": data.get("topic_name"),
            "partitions_count": data.get("partitions_count"),
            "replication_factor": data.get("replication_factor"),
            "is_internal": data.get("is_internal"),
            "cluster_id": data.get("cluster_id"),
        }

    @mcp.tool()
    def kafka_create_topic(
        topic_name: str,
        partitions_count: int = 1,
        replication_factor: int = 3,
    ) -> dict:
        """Create a new Kafka topic.

        Args:
            topic_name: The topic name.
            partitions_count: Number of partitions (default 1).
            replication_factor: Replication factor (default 3).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg
        if not topic_name:
            return {"error": "topic_name is required"}

        payload = {
            "topic_name": topic_name,
            "partitions_count": partitions_count,
            "replication_factor": replication_factor,
        }

        data = _post(f"{base_url}/topics", headers, payload)
        if "error" in data:
            return data

        return {
            "name": data.get("topic_name"),
            "partitions_count": data.get("partitions_count"),
            "replication_factor": data.get("replication_factor"),
        }

    @mcp.tool()
    def kafka_produce_message(
        topic_name: str,
        value: str,
        key: str = "",
        value_type: str = "JSON",
    ) -> dict:
        """Produce a message to a Kafka topic.

        Args:
            topic_name: The topic to produce to.
            value: The message value (string or JSON).
            key: Optional message key.
            value_type: Value serialization type: JSON, STRING, or BINARY (default JSON).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg
        if not topic_name or not value:
            return {"error": "topic_name and value are required"}

        payload: dict[str, Any] = {
            "value": {"type": value_type, "data": value},
        }
        if key:
            payload["key"] = {"type": "STRING", "data": key}

        data = _post(f"{base_url}/topics/{topic_name}/records", headers, payload)
        if "error" in data:
            return data

        return {
            "topic": data.get("topic_name"),
            "partition": data.get("partition_id"),
            "offset": data.get("offset"),
            "timestamp": data.get("timestamp"),
        }

    @mcp.tool()
    def kafka_list_consumer_groups() -> dict:
        """List all consumer groups in the Kafka cluster."""
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg

        data = _get(f"{base_url}/consumer-groups", headers)
        if "error" in data:
            return data

        groups = data.get("data", [])
        return {
            "count": len(groups),
            "consumer_groups": [
                {
                    "id": g.get("consumer_group_id"),
                    "is_simple": g.get("is_simple"),
                    "state": g.get("state"),
                    "coordinator_id": g.get("coordinator", {}).get("related") if isinstance(g.get("coordinator"), dict) else None,
                }
                for g in groups
            ],
        }

    @mcp.tool()
    def kafka_get_consumer_group_lag(consumer_group_id: str) -> dict:
        """Get lag summary for a Kafka consumer group.

        Args:
            consumer_group_id: The consumer group ID.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        base_url, cluster_id, headers = cfg
        if not consumer_group_id:
            return {"error": "consumer_group_id is required"}

        data = _get(f"{base_url}/consumer-groups/{consumer_group_id}/lag-summary", headers)
        if "error" in data:
            return data

        return {
            "consumer_group_id": data.get("consumer_group_id"),
            "max_lag": data.get("max_lag"),
            "max_lag_topic": data.get("max_lag_topic_name"),
            "max_lag_partition": data.get("max_lag_partition_id"),
            "max_lag_consumer_id": data.get("max_lag_consumer_id"),
            "total_lag": data.get("total_lag"),
        }
