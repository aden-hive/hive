"""
Tests for the Langfuse / OTel integration in framework.observability.logging.

These tests verify the integration using mocks so the OTel packages are not
required in the test environment.  Each test resets module-level state after
running to avoid cross-test contamination.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

import framework.observability.logging as obs

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _reset_otel_state() -> None:
    """Reset module-level Langfuse/OTel state between tests."""
    obs._otel_tracer = None
    obs._otel_span_stack.clear()
    from framework.observability.logging import trace_context

    trace_context.set(None)


@pytest.fixture(autouse=True)
def clean_otel_state():
    """Automatically reset OTel state before and after every test."""
    _reset_otel_state()
    yield
    _reset_otel_state()


# ─── configure_langfuse() ─────────────────────────────────────────────────────


class TestConfigureLangfuse:
    def test_no_op_when_packages_missing(self, caplog):
        """configure_langfuse() warns and exits cleanly when OTel packages are not installed."""
        missing = {
            "opentelemetry": None,
            "opentelemetry.trace": None,
            "opentelemetry.exporter": None,
            "opentelemetry.exporter.otlp": None,
            "opentelemetry.exporter.otlp.proto": None,
            "opentelemetry.exporter.otlp.proto.http": None,
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.resources": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
        }
        with patch.dict("sys.modules", missing):
            with caplog.at_level(logging.WARNING, logger="framework.observability.logging"):
                obs.configure_langfuse(public_key="pk", secret_key="sk")

        assert obs._otel_tracer is None
        assert "framework[langfuse]" in caplog.text

    def test_no_op_when_keys_missing(self, caplog):
        """configure_langfuse() warns and exits when credentials are absent."""
        mock_otel = MagicMock()
        modules = {
            "opentelemetry": mock_otel,
            "opentelemetry.trace": MagicMock(),
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": MagicMock(),
            "opentelemetry.sdk.resources": MagicMock(),
            "opentelemetry.sdk.trace": MagicMock(),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }
        with patch.dict("sys.modules", modules):
            with patch.dict("os.environ", {}, clear=True):
                with caplog.at_level(logging.WARNING, logger="framework.observability.logging"):
                    obs.configure_langfuse()  # no keys passed, none in env

        assert obs._otel_tracer is None
        assert "LANGFUSE_PUBLIC_KEY" in caplog.text

    def test_reads_keys_from_env(self):
        """configure_langfuse() picks up keys from environment variables."""
        mock_tracer = MagicMock()
        mock_provider = MagicMock()
        mock_provider.get_tracer.return_value = mock_tracer

        MockTracerProvider = MagicMock(return_value=mock_provider)
        MockOTLPSpanExporter = MagicMock()
        MockBatchSpanProcessor = MagicMock()
        mock_resource = MagicMock()
        MockResource = MagicMock()
        MockResource.create.return_value = mock_resource
        mock_otel_trace = MagicMock()

        modules = {
            "opentelemetry.trace": mock_otel_trace,
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": MagicMock(
                OTLPSpanExporter=MockOTLPSpanExporter
            ),
            "opentelemetry.sdk.resources": MagicMock(Resource=MockResource),
            "opentelemetry.sdk.trace": MagicMock(TracerProvider=MockTracerProvider),
            "opentelemetry.sdk.trace.export": MagicMock(BatchSpanProcessor=MockBatchSpanProcessor),
        }
        with patch.dict("sys.modules", modules):
            with patch.dict(
                "os.environ",
                {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"},
            ):
                with patch("base64.b64encode", return_value=b"dGVzdA=="):
                    obs.configure_langfuse()

        assert obs._otel_tracer is mock_tracer

    def test_custom_host_used_in_endpoint(self):
        """configure_langfuse() builds the OTLP endpoint from the supplied host."""
        captured_endpoint: list[str] = []

        def fake_exporter(endpoint, headers):
            captured_endpoint.append(endpoint)
            return MagicMock()

        mock_provider = MagicMock()
        mock_provider.get_tracer.return_value = MagicMock()
        MockTracerProvider = MagicMock(return_value=mock_provider)
        MockResource = MagicMock()
        MockResource.create.return_value = MagicMock()

        modules = {
            "opentelemetry.trace": MagicMock(),
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": MagicMock(
                OTLPSpanExporter=fake_exporter
            ),
            "opentelemetry.sdk.resources": MagicMock(Resource=MockResource),
            "opentelemetry.sdk.trace": MagicMock(TracerProvider=MockTracerProvider),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }
        with patch.dict("sys.modules", modules):
            with patch("base64.b64encode", return_value=b"dGVzdA=="):
                obs.configure_langfuse(
                    public_key="pk",
                    secret_key="sk",
                    host="http://localhost:3000",
                )

        assert captured_endpoint == ["http://localhost:3000/api/public/otel/v1/traces"]

    def test_trailing_slash_stripped_from_host(self):
        """configure_langfuse() strips trailing slashes from the host URL."""
        captured_endpoint: list[str] = []

        def fake_exporter(endpoint, headers):
            captured_endpoint.append(endpoint)
            return MagicMock()

        mock_provider = MagicMock()
        mock_provider.get_tracer.return_value = MagicMock()

        modules = {
            "opentelemetry.trace": MagicMock(),
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": MagicMock(
                OTLPSpanExporter=fake_exporter
            ),
            "opentelemetry.sdk.resources": MagicMock(Resource=MagicMock(create=MagicMock())),
            "opentelemetry.sdk.trace": MagicMock(
                TracerProvider=MagicMock(return_value=mock_provider)
            ),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }
        with patch.dict("sys.modules", modules):
            with patch("base64.b64encode", return_value=b"dGVzdA=="):
                obs.configure_langfuse(
                    public_key="pk",
                    secret_key="sk",
                    host="https://cloud.langfuse.com/",
                )

        assert "//api" not in captured_endpoint[0]
        assert captured_endpoint[0].startswith("https://cloud.langfuse.com/api")


# ─── set_trace_context() + _otel_open_trace() ────────────────────────────────


class TestSetTraceContextOtel:
    def _install_mock_tracer(self) -> MagicMock:
        """Inject a mock tracer and return it."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        obs._otel_tracer = mock_tracer
        return mock_tracer

    def test_open_trace_called_on_first_trace_id(self):
        """set_trace_context with trace_id opens an OTel span."""
        self._install_mock_tracer()

        with patch("framework.observability.logging._otel_open_trace") as mock_open:
            obs.set_trace_context(
                trace_id="a" * 32,
                execution_id="b" * 32,
                goal_id="test-goal",
            )
            mock_open.assert_called_once_with("a" * 32, "test-goal")

    def test_enrich_span_called_without_trace_id(self):
        """set_trace_context without trace_id enriches the span via _otel_enrich_span."""
        self._install_mock_tracer()
        # Pre-seed context so there is an active trace
        obs.trace_context.set({"trace_id": "a" * 32})

        with patch("framework.observability.logging._otel_enrich_span") as mock_enrich:
            obs.set_trace_context(agent_id="my-agent")
            mock_enrich.assert_called_once_with({"agent_id": "my-agent"})

    def test_enrich_span_uses_stack_not_thread_local(self):
        """_otel_enrich_span targets the span in _otel_span_stack, not the thread-local span."""
        self._install_mock_tracer()
        trace_id = "a" * 32
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        obs._otel_span_stack[trace_id] = (mock_span, MagicMock())
        obs.trace_context.set({"trace_id": trace_id})

        obs._otel_enrich_span({"agent_id": "my-agent", "goal_id": "test"})

        mock_span.set_attribute.assert_any_call("hive.agent_id", "my-agent")
        mock_span.set_attribute.assert_any_call("hive.goal_id", "test")

    def test_no_otel_calls_when_tracer_not_configured(self):
        """set_trace_context does not touch OTel when configure_langfuse() was not called."""
        assert obs._otel_tracer is None  # confirm baseline

        with patch("framework.observability.logging._otel_open_trace") as mock_open:
            with patch("framework.observability.logging._otel_enrich_span") as mock_enrich:
                obs.set_trace_context(trace_id="a" * 32, goal_id="g")
                mock_open.assert_not_called()
                mock_enrich.assert_not_called()

    def test_duplicate_trace_id_does_not_open_second_span(self):
        """_otel_open_trace is idempotent — a second call with the same trace_id is a no-op."""
        self._install_mock_tracer()
        trace_id = "c" * 32

        # Seed stack as if already open
        sentinel_span = MagicMock()
        sentinel_token = MagicMock()
        obs._otel_span_stack[trace_id] = (sentinel_span, sentinel_token)

        with patch(
            "opentelemetry.trace.NonRecordingSpan", MagicMock()
        ), patch("opentelemetry.trace.set_span_in_context", MagicMock()):
            obs._otel_open_trace(trace_id, "goal")

        # Span in stack must be the original sentinel, not a new one.
        assert obs._otel_span_stack[trace_id][0] is sentinel_span


# ─── clear_trace_context() + _otel_close_trace() ─────────────────────────────


class TestClearTraceContextOtel:
    def test_closes_span_when_langfuse_enabled(self):
        """clear_trace_context() ends the OTel span when Langfuse is configured."""
        obs._otel_tracer = MagicMock()  # mark as enabled
        trace_id = "d" * 32
        mock_span = MagicMock()
        mock_token = MagicMock()
        obs._otel_span_stack[trace_id] = (mock_span, mock_token)
        obs.trace_context.set({"trace_id": trace_id})

        with patch("opentelemetry.context.detach") as mock_detach:
            obs.clear_trace_context()

        mock_span.end.assert_called_once()
        mock_detach.assert_called_once_with(mock_token)
        assert trace_id not in obs._otel_span_stack
        assert obs.trace_context.get() is None

    def test_no_error_when_langfuse_not_configured(self):
        """clear_trace_context() is safe to call even without Langfuse enabled."""
        obs.trace_context.set({"trace_id": "e" * 32})
        obs.clear_trace_context()  # must not raise
        assert obs.trace_context.get() is None

    def test_no_error_when_span_already_gone(self):
        """_otel_close_trace() is safe when the span is not in the stack."""
        obs._otel_tracer = MagicMock()
        obs.trace_context.set({"trace_id": "f" * 32})
        # _otel_span_stack is empty — should not raise
        obs.clear_trace_context()
