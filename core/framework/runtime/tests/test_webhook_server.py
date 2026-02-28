"""
Tests for WebhookServer and event-driven entry points.
"""

import asyncio
import hashlib
import hmac as hmac_mod
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import aiohttp
import pytest

from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.webhook_server import (
    WebhookRoute,
    WebhookServer,
    WebhookServerConfig,
)


def _make_server(event_bus: EventBus, routes: list[WebhookRoute] | None = None):
    """Helper to create a WebhookServer with port=0 for OS-assigned port."""
    config = WebhookServerConfig(host="127.0.0.1", port=0)
    server = WebhookServer(event_bus, config)
    for route in routes or []:
        server.add_route(route)
    return server


def _base_url(server: WebhookServer) -> str:
    """Get the base URL for a running server."""
    return f"http://127.0.0.1:{server.port}"


class TestWebhookServerLifecycle:
    """Tests for server start/stop."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        bus = EventBus()
        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="test", path="/webhooks/test", methods=["POST"]),
            ],
        )

        await server.start()
        assert server.is_running
        assert server.port is not None

        await server.stop()
        assert not server.is_running
        assert server.port is None

    @pytest.mark.asyncio
    async def test_no_routes_skips_start(self):
        bus = EventBus()
        server = _make_server(bus)  # no routes

        await server.start()
        assert not server.is_running

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        bus = EventBus()
        server = _make_server(bus)

        # Should be a no-op, not raise
        await server.stop()
        assert not server.is_running


class TestWebhookEventPublishing:
    """Tests for HTTP request -> EventBus event publishing."""

    @pytest.mark.asyncio
    async def test_post_publishes_webhook_received(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="gh", path="/webhooks/github", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/github",
                    json={"action": "opened", "number": 42},
                ) as resp:
                    assert resp.status == 202
                    body = await resp.json()
                    assert body["status"] == "accepted"

            # Give event bus time to dispatch
            await asyncio.sleep(0.05)

            assert len(received) == 1
            event = received[0]
            assert event.type == EventType.WEBHOOK_RECEIVED
            assert event.stream_id == "gh"
            assert event.data["path"] == "/webhooks/github"
            assert event.data["method"] == "POST"
            assert event.data["payload"] == {"action": "opened", "number": 42}
            assert isinstance(event.data["headers"], dict)
            assert event.data["query_params"] == {}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_query_params_included(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="hook", path="/webhooks/hook", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/hook?source=test&v=2",
                    json={"data": "hello"},
                ) as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)

            assert len(received) == 1
            assert received[0].data["query_params"] == {"source": "test", "v": "2"}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_non_json_body(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="raw", path="/webhooks/raw", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/raw",
                    data=b"plain text body",
                    headers={"Content-Type": "text/plain"},
                ) as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)

            assert len(received) == 1
            assert received[0].data["payload"] == {"raw_body": "plain text body"}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_empty_body(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="empty", path="/webhooks/empty", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{_base_url(server)}/webhooks/empty") as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)

            assert len(received) == 1
            assert received[0].data["payload"] == {}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_multiple_routes(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="a", path="/webhooks/a", methods=["POST"]),
                WebhookRoute(source_id="b", path="/webhooks/b", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/a", json={"from": "a"}
                ) as resp:
                    assert resp.status == 202

                async with session.post(
                    f"{_base_url(server)}/webhooks/b", json={"from": "b"}
                ) as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)

            assert len(received) == 2
            stream_ids = {e.stream_id for e in received}
            assert stream_ids == {"a", "b"}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_filter_stream_subscription(self):
        """Subscribers can filter by stream_id (source_id)."""
        bus = EventBus()
        a_events = []
        b_events = []

        async def handle_a(event):
            a_events.append(event)

        async def handle_b(event):
            b_events.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handle_a, filter_stream="a")
        bus.subscribe([EventType.WEBHOOK_RECEIVED], handle_b, filter_stream="b")

        server = _make_server(
            bus,
            [
                WebhookRoute(source_id="a", path="/webhooks/a", methods=["POST"]),
                WebhookRoute(source_id="b", path="/webhooks/b", methods=["POST"]),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(f"{_base_url(server)}/webhooks/a", json={"x": 1})
                await session.post(f"{_base_url(server)}/webhooks/b", json={"x": 2})

            await asyncio.sleep(0.05)

            assert len(a_events) == 1
            assert a_events[0].data["payload"] == {"x": 1}
            assert len(b_events) == 1
            assert b_events[0].data["payload"] == {"x": 2}
        finally:
            await server.stop()


class TestHMACVerification:
    """Tests for HMAC-SHA256 signature verification."""

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        secret = "test-secret-key"
        server = _make_server(
            bus,
            [
                WebhookRoute(
                    source_id="secure",
                    path="/webhooks/secure",
                    methods=["POST"],
                    secret=secret,
                ),
            ],
        )
        await server.start()

        try:
            body = json.dumps({"event": "push"}).encode()
            sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/secure",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": f"sha256={sig}",
                    },
                ) as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)
            assert len(received) == 1
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(
                    source_id="secure",
                    path="/webhooks/secure",
                    methods=["POST"],
                    secret="real-secret",
                ),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/secure",
                    json={"event": "push"},
                    headers={"X-Hub-Signature-256": "sha256=invalidsignature"},
                ) as resp:
                    assert resp.status == 401

            await asyncio.sleep(0.05)
            assert len(received) == 0  # No event published
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(
                    source_id="secure",
                    path="/webhooks/secure",
                    methods=["POST"],
                    secret="my-secret",
                ),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                # No X-Hub-Signature-256 header
                async with session.post(
                    f"{_base_url(server)}/webhooks/secure",
                    json={"event": "push"},
                ) as resp:
                    assert resp.status == 401

            await asyncio.sleep(0.05)
            assert len(received) == 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_no_secret_skips_verification(self):
        """Routes without a secret accept any request."""
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe([EventType.WEBHOOK_RECEIVED], handler)

        server = _make_server(
            bus,
            [
                WebhookRoute(
                    source_id="open",
                    path="/webhooks/open",
                    methods=["POST"],
                    secret=None,
                ),
            ],
        )
        await server.start()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_base_url(server)}/webhooks/open",
                    json={"data": "test"},
                ) as resp:
                    assert resp.status == 202

            await asyncio.sleep(0.05)
            assert len(received) == 1
        finally:
            await server.stop()


class TestEventDrivenEntryPoints:
    """Tests for event-driven entry points wired through AgentRuntime."""

    def _make_graph_and_goal(self):
        """Minimal graph + goal for testing entry point triggering."""
        from framework.graph import Goal
        from framework.graph.edge import GraphSpec
        from framework.graph.goal import SuccessCriterion
        from framework.graph.node import NodeSpec

        nodes = [
            NodeSpec(
                id="process-event",
                name="Process Event",
                description="Process incoming event",
                node_type="event_loop",
                input_keys=["event"],
                output_keys=["result"],
            ),
        ]
        graph = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            version="1.0.0",
            entry_node="process-event",
            entry_points={"start": "process-event"},
            async_entry_points=[],
            terminal_nodes=[],
            pause_nodes=[],
            nodes=nodes,
            edges=[],
        )
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="Test",
            success_criteria=[
                SuccessCriterion(
                    id="sc-1",
                    description="Done",
                    metric="done",
                    target="yes",
                    weight=1.0,
                ),
            ],
        )
        return graph, goal

    @pytest.mark.asyncio
    async def test_event_entry_point_subscribes_to_bus(self):
        """Entry point with trigger_type='event' subscribes and triggers on matching events."""
        graph, goal = self._make_graph_and_goal()

        config = AgentRuntimeConfig(
            webhook_host="127.0.0.1",
            webhook_port=0,
            webhook_routes=[
                {"source_id": "gh", "path": "/webhooks/github"},
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
                config=config,
            )

            runtime.register_entry_point(
                EntryPointSpec(
                    id="gh-handler",
                    name="GitHub Handler",
                    entry_node="process-event",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["webhook_received"],
                        "filter_stream": "gh",
                    },
                )
            )

            trigger_calls = []

            async def mock_trigger(ep_id, data, **kwargs):
                trigger_calls.append((ep_id, data))

            with patch.object(runtime, "trigger", side_effect=mock_trigger):
                await runtime.start()

                try:
                    assert runtime.webhook_server is not None
                    assert runtime.webhook_server.is_running

                    port = runtime.webhook_server.port
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"http://127.0.0.1:{port}/webhooks/github",
                            json={"action": "push", "ref": "main"},
                        ) as resp:
                            assert resp.status == 202

                    await asyncio.sleep(0.1)

                    assert len(trigger_calls) == 1
                    ep_id, data = trigger_calls[0]
                    assert ep_id == "gh-handler"
                    assert "event" in data
                    assert data["event"]["type"] == "webhook_received"
                    assert data["event"]["stream_id"] == "gh"
                    assert data["event"]["data"]["payload"] == {
                        "action": "push",
                        "ref": "main",
                    }
                finally:
                    await runtime.stop()

            assert runtime.webhook_server is None

    @pytest.mark.asyncio
    async def test_event_entry_point_filter_stream(self):
        """Entry point only triggers for matching stream_id (source_id)."""
        graph, goal = self._make_graph_and_goal()

        config = AgentRuntimeConfig(
            webhook_routes=[
                {"source_id": "github", "path": "/webhooks/github"},
                {"source_id": "stripe", "path": "/webhooks/stripe"},
            ],
            webhook_port=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
                config=config,
            )

            runtime.register_entry_point(
                EntryPointSpec(
                    id="gh-only",
                    name="GitHub Only",
                    entry_node="process-event",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["webhook_received"],
                        "filter_stream": "github",
                    },
                )
            )

            trigger_calls = []

            async def mock_trigger(ep_id, data, **kwargs):
                trigger_calls.append((ep_id, data))

            with patch.object(runtime, "trigger", side_effect=mock_trigger):
                await runtime.start()

                try:
                    port = runtime.webhook_server.port
                    async with aiohttp.ClientSession() as session:
                        # POST to stripe — should NOT trigger
                        await session.post(
                            f"http://127.0.0.1:{port}/webhooks/stripe",
                            json={"type": "payment"},
                        )
                        # POST to github — should trigger
                        await session.post(
                            f"http://127.0.0.1:{port}/webhooks/github",
                            json={"action": "opened"},
                        )

                    await asyncio.sleep(0.1)

                    assert len(trigger_calls) == 1
                    assert trigger_calls[0][0] == "gh-only"
                finally:
                    await runtime.stop()

    @pytest.mark.asyncio
    async def test_no_webhook_routes_skips_server(self):
        """Runtime without webhook_routes does not start a webhook server."""
        graph, goal = self._make_graph_and_goal()

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
            )

            runtime.register_entry_point(
                EntryPointSpec(
                    id="manual",
                    name="Manual",
                    entry_node="process-event",
                    trigger_type="manual",
                )
            )

            await runtime.start()
            try:
                assert runtime.webhook_server is None
            finally:
                await runtime.stop()

    @pytest.mark.asyncio
    async def test_event_entry_point_custom_event(self):
        """Entry point can subscribe to CUSTOM events, not just webhooks."""
        graph, goal = self._make_graph_and_goal()

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
            )

            runtime.register_entry_point(
                EntryPointSpec(
                    id="custom-handler",
                    name="Custom Handler",
                    entry_node="process-event",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["custom"],
                    },
                )
            )

            trigger_calls = []

            async def mock_trigger(ep_id, data, **kwargs):
                trigger_calls.append((ep_id, data))

            with patch.object(runtime, "trigger", side_effect=mock_trigger):
                await runtime.start()

                try:
                    await runtime.event_bus.publish(
                        AgentEvent(
                            type=EventType.CUSTOM,
                            stream_id="some-source",
                            data={"key": "value"},
                        )
                    )

                    await asyncio.sleep(0.1)

                    assert len(trigger_calls) == 1
                    assert trigger_calls[0][0] == "custom-handler"
                    assert trigger_calls[0][1]["event"]["type"] == "custom"
                    assert trigger_calls[0][1]["event"]["data"]["key"] == "value"
                finally:
                    await runtime.stop()
