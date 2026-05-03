"""
Tests for langfuse_tool/tool.py — Hive agent run lifecycle instrumentation.

All Langfuse SDK calls are patched at get_client() so tests run with no
real credentials and no network traffic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-lf-test-key",
    "LANGFUSE_SECRET_KEY": "sk-lf-test-secret",
    "LANGFUSE_HOST": "https://cloud.langfuse.com",
}

PATCH_TARGET = "aden_tools.tools.langfuse_tool.tool.get_client"


def _make_client(trace_id="trace-abc123", span_id="span-xyz789"):
    """Build a fully-mocked Langfuse client whose return values are inspectable."""
    client = MagicMock()

    # create_trace_id returns a string
    client.create_trace_id.return_value = trace_id

    # create_event returns an object with .id
    mock_event = MagicMock()
    mock_event.id = "event-id"
    client.create_event.return_value = mock_event

    # start_observation returns an object with .id
    mock_span = MagicMock()
    mock_span.id = span_id
    client.start_observation.return_value = mock_span

    # create_score returns None in v3
    client.create_score.return_value = None

    return client


# ---------------------------------------------------------------------------
# Import the three functions under test
# ---------------------------------------------------------------------------

from aden_tools.tools.langfuse_tool.tool import (
    log_node_span,
    score_agent_run,
    start_agent_trace,
)


# ===========================================================================
# start_agent_trace
# ===========================================================================


class TestStartAgentTrace:
    def test_returns_trace_id(self):
        """start_agent_trace must return the trace ID string from the SDK."""
        mock_client = _make_client(trace_id="trace-001")
        with patch(PATCH_TARGET, return_value=mock_client):
            result = start_agent_trace(
                agent_name="research-agent",
                session_id="session-42",
                input_data={"query": "Summarise earnings"},
            )
        assert result == "trace-001"

    def test_calls_create_event_with_correct_args(self):
        """start_agent_trace must call lf.create_trace_id and lf.create_event with trace metadata."""
        mock_client = _make_client(trace_id="trace-99")
        with patch(PATCH_TARGET, return_value=mock_client):
            start_agent_trace(
                agent_name="my-agent",
                session_id="sess-99",
                input_data={"key": "value"},
                user_id="user-7",
                tags=["prod", "v2"],
            )

        mock_client.create_trace_id.assert_called_once()
        mock_client.create_event.assert_called_once_with(
            name="my-agent",
            input={"key": "value"},
            trace_context={"trace_id": "trace-99"},
        )

    def test_empty_user_id_propagation(self):
        """An empty user_id should still trigger propagate_attributes (handled by start_agent_trace)."""
        mock_client = _make_client()
        # We patch propagate_attributes to verify it's called
        with (
            patch(PATCH_TARGET, return_value=mock_client),
            patch("aden_tools.tools.langfuse_tool.tool.propagate_attributes") as mock_prop,
        ):
            start_agent_trace(
                agent_name="agent",
                session_id="s1",
                input_data={},
                user_id="",
            )

        mock_prop.assert_called_once()
        _kwargs = mock_prop.call_args.kwargs
        assert _kwargs["user_id"] is None

    def test_default_tags_propagation(self):
        """When tags is omitted, an empty list should be propagated."""
        mock_client = _make_client()
        with (
            patch(PATCH_TARGET, return_value=mock_client),
            patch("aden_tools.tools.langfuse_tool.tool.propagate_attributes") as mock_prop,
        ):
            start_agent_trace(agent_name="agent", session_id="s1", input_data={})

        _kwargs = mock_prop.call_args.kwargs
        assert _kwargs["tags"] == []

    def test_does_not_call_flush(self):
        """start_agent_trace must NOT flush — flushing before any node runs wastes latency."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            start_agent_trace("agent", "s1", {})

        mock_client.flush.assert_not_called()


# ===========================================================================
# log_node_span
# ===========================================================================


class TestLogNodeSpan:
    def test_returns_span_id(self):
        """log_node_span must return the span ID from the SDK."""
        mock_client = _make_client(span_id="span-001")
        with patch(PATCH_TARGET, return_value=mock_client):
            result = log_node_span(
                trace_id="trace-abc",
                node_name="web_search",
                input={"query": "Tesla Q1"},
                output={"results": ["..."]},
            )
        assert result == "span-001"

    def test_calls_observation_with_required_args(self):
        """log_node_span must call start_observation with required trace context."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(
                trace_id="trace-abc",
                node_name="summarise",
                input={"text": "long article"},
                output={"summary": "short"},
            )

        call_kwargs = mock_client.start_observation.call_args.kwargs
        assert call_kwargs["trace_context"] == {"trace_id": "trace-abc"}
        assert call_kwargs["name"] == "summarise"
        assert call_kwargs["input"] == {"text": "long article"}
        assert call_kwargs["output"] == {"summary": "short"}

    def test_latency_stored_in_metadata(self):
        """Latency in ms should land in metadata (Langfuse derives latency from timestamps)."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(
                trace_id="t1",
                node_name="node",
                input={},
                output={},
                latency_ms=342.7,
            )

        call_kwargs = mock_client.start_observation.call_args.kwargs
        assert call_kwargs["metadata"]["latency_ms"] == 342.7

    def test_token_counts_forwarded(self):
        """Token dict should be translated into Langfuse usage format."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(
                trace_id="t1",
                node_name="node",
                input={},
                output={},
                tokens={"input": 100, "output": 50, "total": 150},
            )

        usage = mock_client.start_observation.call_args.kwargs["usage_details"]
        assert usage["input"] == 100
        assert usage["output"] == 50
        assert usage["total"] == 150

    def test_token_total_computed_when_missing(self):
        """If 'total' is absent from tokens, it must be computed as input+output."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(
                trace_id="t1",
                node_name="node",
                input={},
                output={},
                tokens={"input": 200, "output": 75},
            )

        usage = mock_client.start_observation.call_args.kwargs["usage_details"]
        assert usage["total"] == 275

    def test_no_tokens_passes_none_usage(self):
        """When tokens is omitted, usage must be None (not an empty dict)."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(trace_id="t1", node_name="n", input={}, output={})

        usage = mock_client.start_observation.call_args.kwargs["usage_details"]
        assert usage is None

    def test_empty_model_becomes_none(self):
        """An empty model string should be passed as None to avoid polluting UI."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(
                trace_id="t1",
                node_name="n",
                input={},
                output={},
                model="",
            )

        call_kwargs = mock_client.start_observation.call_args.kwargs
        assert call_kwargs["model"] is None

    def test_flush_called_after_span(self):
        """CRITICAL: flush() must be called after every span to prevent data loss."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(trace_id="t1", node_name="n", input={}, output={})

        mock_client.flush.assert_called_once()

    def test_flush_called_after_span_not_before(self):
        """flush() must come after start_observation() — correct ordering guarantees delivery."""
        mock_client = _make_client()
        call_order = []
        mock_client.start_observation.side_effect = lambda **_: call_order.append("span") or MagicMock(id="s1")
        mock_client.flush.side_effect = lambda: call_order.append("flush")

        with patch(PATCH_TARGET, return_value=mock_client):
            log_node_span(trace_id="t1", node_name="n", input={}, output={})

        assert call_order == ["span", "flush"]

    def test_multiple_spans_same_trace(self):
        """Three nodes → three spans, all under the same trace_id."""
        mock_client = _make_client()
        span_ids = ["span-1", "span-2", "span-3"]
        side_effects = []
        for sid in span_ids:
            m = MagicMock()
            m.id = sid
            side_effects.append(m)
        mock_client.start_observation.side_effect = side_effects

        with patch(PATCH_TARGET, return_value=mock_client):
            r1 = log_node_span("trace-X", "node1", {}, {})
            r2 = log_node_span("trace-X", "node2", {}, {})
            r3 = log_node_span("trace-X", "node3", {}, {})

        assert [r1, r2, r3] == ["span-1", "span-2", "span-3"]
        # flush must have been called once per span
        assert mock_client.flush.call_count == 3
        # All spans share the same trace_id
        for c in mock_client.start_observation.call_args_list:
            assert c.kwargs["trace_context"]["trace_id"] == "trace-X"


# ===========================================================================
# score_agent_run
# ===========================================================================


class TestScoreAgentRun:
    def test_returns_trace_id(self):
        """score_agent_run must return the trace ID in v3."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            result = score_agent_run(
                trace_id="trace-abc",
                score_name="quality",
                score_value=0.87,
            )
        assert result == "trace-abc"

    def test_calls_score_with_correct_args(self):
        """score_agent_run must forward trace_id, name, value, and comment to lf.score()."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            score_agent_run(
                trace_id="trace-abc",
                score_name="correctness",
                score_value=0.95,
                comment="Excellent output",
            )

        mock_client.create_score.assert_called_once_with(
            trace_id="trace-abc",
            name="correctness",
            value=0.95,
            comment="Excellent output",
        )

    def test_empty_comment_becomes_none(self):
        """An empty comment string should be passed as None to keep the score record clean."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            score_agent_run(
                trace_id="trace-abc",
                score_name="quality",
                score_value=0.5,
                comment="",
            )

        call_kwargs = mock_client.create_score.call_args.kwargs
        assert call_kwargs["comment"] is None

    def test_flush_called_after_score(self):
        """CRITICAL: flush() must be called after scoring or the score can be lost."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            score_agent_run("trace-abc", "quality", 1.0)

        mock_client.flush.assert_called_once()

    def test_flush_called_after_score_not_before(self):
        """flush() must come after score() — correct ordering guarantees delivery."""
        mock_client = _make_client()
        call_order = []
        mock_client.create_score.side_effect = lambda **_: call_order.append("score")
        mock_client.flush.side_effect = lambda: call_order.append("flush")

        with patch(PATCH_TARGET, return_value=mock_client):
            score_agent_run("trace-abc", "quality", 0.9)

        assert call_order == ["score", "flush"]

    @pytest.mark.parametrize("value", [-0.1, 1.1, "not-a-number"])
    def test_score_invalid_values(self, value):
        """score_agent_run must raise ValueError for scores outside [0, 1] or non-numeric types."""
        mock_client = _make_client()
        with (
            patch(PATCH_TARGET, return_value=mock_client),
            pytest.raises(ValueError, match=r"score_value must be a number in \[0, 1\]"),
        ):
            score_agent_run("trace-abc", "quality", value)

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_score_boundary_values(self, value):
        """Score values 0.0, 0.5, and 1.0 (the full valid range) must all be accepted."""
        mock_client = _make_client()
        with patch(PATCH_TARGET, return_value=mock_client):
            score_agent_run("trace-abc", "quality", value)

        call_kwargs = mock_client.create_score.call_args.kwargs
        assert call_kwargs["value"] == value


# ===========================================================================
# Full lifecycle integration (unit-level, no network)
# ===========================================================================


class TestFullLifecycle:
    def test_complete_agent_run(self):
        """
        Simulate a 3-node agent run end-to-end using mocks:
          start_agent_trace → 3x log_node_span → score_agent_run

        Validates that trace_id threads correctly through all calls.
        """
        mock_client = _make_client(
            trace_id="trace-lifecycle",
            span_id="span-base",
        )

        # Give each span call a unique id
        span_side = []
        for i in range(1, 4):
            m = MagicMock()
            m.id = f"span-{i}"
            span_side.append(m)
        mock_client.start_observation.side_effect = span_side

        with patch(PATCH_TARGET, return_value=mock_client):
            # 1. Open trace
            trace_id = start_agent_trace(
                agent_name="test-agent",
                session_id="sess-lifecycle",
                input_data={"goal": "test"},
            )

            # 2. Three nodes
            s1 = log_node_span(trace_id, "fetch", {"url": "..."}, {"html": "..."})
            s2 = log_node_span(trace_id, "parse", {"html": "..."}, {"data": {}})
            s3 = log_node_span(trace_id, "summarise", {"data": {}}, {"summary": "done"})

            # 3. Final score
            score_id = score_agent_run(trace_id, "quality", 0.9, "Solid run")

        # Correct IDs returned
        assert trace_id == "trace-lifecycle"
        assert [s1, s2, s3] == ["span-1", "span-2", "span-3"]
        assert score_id == "trace-lifecycle"

        # create_trace_id called once, start_observation 3 times (+1 event), create_score once
        mock_client.create_trace_id.assert_called_once()
        assert mock_client.start_observation.call_count == 3
        mock_client.create_score.assert_called_once()

        # flush() called exactly 4 times: once per span + once for score
        # (start_agent_trace must NOT flush)
        assert mock_client.flush.call_count == 4

        # All spans carry the same trace_id
        for c in mock_client.start_observation.call_args_list:
            assert c.kwargs["trace_context"]["trace_id"] == "trace-lifecycle"

        # Score carries the same trace_id
        assert mock_client.create_score.call_args.kwargs["trace_id"] == "trace-lifecycle"
