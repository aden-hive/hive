"""
Unit tests for the observability framework.

Tests cover:
- ObservabilityConfig configuration
- ObservabilityHooks protocol implementations
- ConsoleExporter and FileExporter
- CompositeHooks delegation
"""

import asyncio
import json
import tempfile
from datetime import datetime
from io import StringIO
from pathlib import Path

import pytest

from framework.observability import (
    CompositeHooks,
    NoOpHooks,
    ObservabilityConfig,
    ObservabilityHooks,
    TelemetryConfig,
)
from framework.observability.exporters.console import ConsoleExporter
from framework.observability.exporters.file import FileExporter
from framework.observability.types import (
    DecisionData,
    EdgeTraversalData,
    LLMCallData,
    NodeContext,
    NodeResult,
    RetryData,
    RunContext,
    RunOutcome,
    ToolCallData,
)


class TestObservabilityConfig:
    """Tests for ObservabilityConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ObservabilityConfig()
        assert config.enabled is True
        assert config.sample_rate == 1.0
        assert config.trace_enabled is True
        assert config.metrics_enabled is True
        assert config.log_sensitive_data is False
        assert config.service_name == "hive-agent"

    def test_dev_config(self) -> None:
        """Test development configuration factory."""
        config = ObservabilityConfig.dev()
        assert config.enabled is True
        assert config.sample_rate == 1.0
        assert config.log_sensitive_data is True

    def test_production_config(self) -> None:
        """Test production configuration factory."""
        config = ObservabilityConfig.production(
            otlp_endpoint="http://localhost:4317",
            prometheus_port=9090,
            sample_rate=0.1,
        )
        assert config.enabled is True
        assert config.otlp_endpoint == "http://localhost:4317"
        assert config.prometheus_port == 9090
        assert config.sample_rate == 0.1
        assert config.log_sensitive_data is False

    def test_disabled_config(self) -> None:
        """Test disabled configuration factory."""
        config = ObservabilityConfig.disabled()
        assert config.enabled is False
        assert config.sample_rate == 0.0

    def test_invalid_sample_rate(self) -> None:
        """Test that invalid sample rates raise errors."""
        with pytest.raises(ValueError):
            ObservabilityConfig(sample_rate=1.5)
        with pytest.raises(ValueError):
            ObservabilityConfig(sample_rate=-0.1)

    def test_string_path_conversion(self) -> None:
        """Test that string paths are converted to Path objects."""
        config = ObservabilityConfig(file_export_path="/tmp/test.jsonl")
        assert isinstance(config.file_export_path, Path)


class TestNoOpHooks:
    """Tests for NoOpHooks."""

    @pytest.fixture
    def hooks(self) -> NoOpHooks:
        return NoOpHooks()

    @pytest.fixture
    def run_context(self) -> RunContext:
        return RunContext(
            run_id="test-run",
            goal_id="test-goal",
            goal_description="Test goal",
        )

    @pytest.fixture
    def node_context(self) -> NodeContext:
        return NodeContext(
            node_id="test-node",
            node_name="Test Node",
            node_type="test",
            run_id="test-run",
        )

    @pytest.fixture
    def node_result(self) -> NodeResult:
        return NodeResult(
            node_id="test-node",
            success=True,
            output={"result": "success"},
        )

    @pytest.fixture
    def run_outcome(self) -> RunOutcome:
        return RunOutcome(
            run_id="test-run",
            success=True,
            narrative="Test completed",
        )

    @pytest.mark.asyncio
    async def test_all_methods_are_noops(
        self,
        hooks: NoOpHooks,
        run_context: RunContext,
        node_context: NodeContext,
        node_result: NodeResult,
        run_outcome: RunOutcome,
    ) -> None:
        """Test that all NoOpHooks methods complete without error."""
        await hooks.on_run_start(run_context)
        await hooks.on_node_start(node_context)
        await hooks.on_node_complete(node_context, node_result)
        await hooks.on_node_error(node_context, "error")
        await hooks.on_decision_made(
            DecisionData(
                decision_id="dec-1",
                node_id="test-node",
                intent="test",
                options=[],
                chosen="opt1",
                reasoning="test",
            )
        )
        await hooks.on_tool_call("tool", {}, "result", node_context)
        await hooks.on_llm_call("model", 10, 20, node_context)
        await hooks.on_edge_traversed(EdgeTraversalData(source_node="a", target_node="b"))
        await hooks.on_retry(
            RetryData(
                node_id="test-node",
                retry_count=1,
                max_retries=3,
            )
        )
        await hooks.on_run_complete(run_context, run_outcome)


class TestConsoleExporter:
    """Tests for ConsoleExporter."""

    @pytest.fixture
    def stream(self) -> StringIO:
        return StringIO()

    @pytest.fixture
    def exporter(self, stream: StringIO) -> ConsoleExporter:
        return ConsoleExporter(verbose=True, colors=False, stream=stream)

    @pytest.fixture
    def run_context(self) -> RunContext:
        return RunContext(
            run_id="test-run",
            goal_id="test-goal",
            goal_description="Test goal description",
        )

    @pytest.fixture
    def node_context(self) -> NodeContext:
        return NodeContext(
            node_id="test-node",
            node_name="Test Node",
            node_type="test",
            run_id="test-run",
        )

    @pytest.fixture
    def node_result(self) -> NodeResult:
        return NodeResult(
            node_id="test-node",
            success=True,
            output={"key": "value"},
            tokens_used=100,
            latency_ms=50,
        )

    @pytest.fixture
    def run_outcome(self) -> RunOutcome:
        return RunOutcome(
            run_id="test-run",
            success=True,
            narrative="Completed successfully",
            total_tokens=100,
            steps_executed=3,
        )

    @pytest.mark.asyncio
    async def test_run_start_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        run_context: RunContext,
    ) -> None:
        """Test that run_start produces output."""
        await exporter.on_run_start(run_context)
        output = stream.getvalue()
        assert "[RUN]" in output
        assert "test-goal" in output

    @pytest.mark.asyncio
    async def test_run_complete_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        run_context: RunContext,
        run_outcome: RunOutcome,
    ) -> None:
        """Test that run_complete produces output."""
        await exporter.on_run_complete(run_context, run_outcome)
        output = stream.getvalue()
        assert "[RUN]" in output
        assert "SUCCESS" in output

    @pytest.mark.asyncio
    async def test_node_start_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        node_context: NodeContext,
    ) -> None:
        """Test that node_start produces output."""
        await exporter.on_node_start(node_context)
        output = stream.getvalue()
        assert "[NODE]" in output
        assert "test-node" in output

    @pytest.mark.asyncio
    async def test_node_complete_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        node_context: NodeContext,
        node_result: NodeResult,
    ) -> None:
        """Test that node_complete produces output with metrics."""
        await exporter.on_node_complete(node_context, node_result)
        output = stream.getvalue()
        assert "[NODE]" in output
        assert "100 tokens" in output
        assert "50ms" in output

    @pytest.mark.asyncio
    async def test_tool_call_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        node_context: NodeContext,
    ) -> None:
        """Test that tool_call produces output."""
        await exporter.on_tool_call(
            "test_tool",
            {"arg": "value"},
            "result",
            node_context,
            latency_ms=25,
        )
        output = stream.getvalue()
        assert "[TOOL]" in output
        assert "test_tool" in output
        assert "25ms" in output

    @pytest.mark.asyncio
    async def test_llm_call_output(
        self,
        exporter: ConsoleExporter,
        stream: StringIO,
        node_context: NodeContext,
    ) -> None:
        """Test that llm_call produces output."""
        await exporter.on_llm_call(
            "claude-3-opus",
            100,
            50,
            node_context,
            latency_ms=200,
            cached_tokens=20,
        )
        output = stream.getvalue()
        assert "[LLM]" in output
        assert "claude-3-opus" in output
        assert "100" in output
        assert "50" in output
        assert "20" in output


class TestFileExporter:
    """Tests for FileExporter."""

    @pytest.fixture
    def temp_file(self) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            yield Path(f.name)
        Path(f.name).unlink(missing_ok=True)

    @pytest.fixture
    def exporter(self, temp_file: Path) -> FileExporter:
        return FileExporter(path=temp_file, include_sensitive=True)

    @pytest.fixture
    def run_context(self) -> RunContext:
        return RunContext(
            run_id="test-run",
            goal_id="test-goal",
            goal_description="Test goal",
            input_data={"key": "value"},
        )

    @pytest.fixture
    def node_context(self) -> NodeContext:
        return NodeContext(
            node_id="test-node",
            node_name="Test Node",
            node_type="test",
            run_id="test-run",
        )

    @pytest.fixture
    def node_result(self) -> NodeResult:
        return NodeResult(
            node_id="test-node",
            success=True,
            output={"result": "ok"},
        )

    @pytest.fixture
    def run_outcome(self) -> RunOutcome:
        return RunOutcome(
            run_id="test-run",
            success=True,
            narrative="Done",
        )

    @pytest.mark.asyncio
    async def test_run_start_writes_json(
        self,
        exporter: FileExporter,
        temp_file: Path,
        run_context: RunContext,
    ) -> None:
        """Test that run_start writes valid JSON Lines."""
        await exporter.on_run_start(run_context)
        exporter.close()

        content = temp_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        event = json.loads(lines[0])
        assert event["event_type"] == "run_start"
        assert event["run_id"] == "test-run"
        assert event["goal_id"] == "test-goal"

    @pytest.mark.asyncio
    async def test_run_complete_writes_json(
        self,
        exporter: FileExporter,
        temp_file: Path,
        run_context: RunContext,
        run_outcome: RunOutcome,
    ) -> None:
        """Test that run_complete writes valid JSON Lines."""
        await exporter.on_run_complete(run_context, run_outcome)
        exporter.close()

        content = temp_file.read_text()
        event = json.loads(content.strip())
        assert event["event_type"] == "run_complete"
        assert event["success"] is True

    @pytest.mark.asyncio
    async def test_node_events_write_json(
        self,
        exporter: FileExporter,
        temp_file: Path,
        node_context: NodeContext,
        node_result: NodeResult,
    ) -> None:
        """Test that node events write valid JSON Lines."""
        await exporter.on_node_start(node_context)
        await exporter.on_node_complete(node_context, node_result)
        exporter.close()

        content = temp_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2

        start_event = json.loads(lines[0])
        assert start_event["event_type"] == "node_start"

        complete_event = json.loads(lines[1])
        assert complete_event["event_type"] == "node_complete"

    @pytest.mark.asyncio
    async def test_sensitive_data_excluded(self, temp_file: Path) -> None:
        """Test that sensitive data is excluded when configured."""
        exporter = FileExporter(path=temp_file, include_sensitive=False)
        run_context = RunContext(
            run_id="test-run",
            goal_id="test-goal",
            input_data={"secret": "password"},
        )

        await exporter.on_run_start(run_context)
        exporter.close()

        content = temp_file.read_text()
        event = json.loads(content.strip())
        assert "input_data" not in event

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, exporter: FileExporter) -> None:
        """Test that close() can be called multiple times."""
        exporter.close()
        exporter.close()


class TestCompositeHooks:
    """Tests for CompositeHooks."""

    @pytest.fixture
    def events(self) -> list[str]:
        return []

    @pytest.fixture
    def tracking_hook(self, events: list[str]) -> ObservabilityHooks:
        """Create a hook that tracks method calls."""

        class TrackingHook(ObservabilityHooks):
            def __init__(self, events_list: list[str]) -> None:
                self.events = events_list

            async def on_run_start(self, context: RunContext) -> None:
                self.events.append("run_start")

            async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
                self.events.append("run_complete")

            async def on_node_start(self, context: NodeContext) -> None:
                self.events.append("node_start")

            async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
                self.events.append("node_complete")

            async def on_node_error(
                self,
                context: NodeContext,
                error: str,
                result: NodeResult | None = None,
            ) -> None:
                self.events.append("node_error")

            async def on_decision_made(self, decision: DecisionData) -> None:
                self.events.append("decision")

            async def on_tool_call(
                self,
                tool_name: str,
                args: dict,
                result: str,
                context: NodeContext,
                is_error: bool = False,
                latency_ms: int = 0,
            ) -> None:
                self.events.append(f"tool:{tool_name}")

            async def on_llm_call(
                self,
                model: str,
                input_tokens: int,
                output_tokens: int,
                context: NodeContext,
                latency_ms: int = 0,
                cached_tokens: int = 0,
                error: str | None = None,
            ) -> None:
                self.events.append(f"llm:{model}")

            async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
                self.events.append("edge")

            async def on_retry(self, data: RetryData) -> None:
                self.events.append("retry")

        return TrackingHook(events)

    @pytest.fixture
    def composite(self, tracking_hook: ObservabilityHooks) -> CompositeHooks:
        return CompositeHooks([tracking_hook])

    @pytest.fixture
    def run_context(self) -> RunContext:
        return RunContext(run_id="test", goal_id="test")

    @pytest.fixture
    def node_context(self) -> NodeContext:
        return NodeContext(
            node_id="test",
            node_name="Test",
            node_type="test",
            run_id="test",
        )

    @pytest.fixture
    def node_result(self) -> NodeResult:
        return NodeResult(node_id="test", success=True)

    @pytest.fixture
    def run_outcome(self) -> RunOutcome:
        return RunOutcome(run_id="test", success=True)

    @pytest.mark.asyncio
    async def test_delegates_to_all_hooks(
        self,
        events: list[str],
        tracking_hook: ObservabilityHooks,
        composite: CompositeHooks,
        run_context: RunContext,
        run_outcome: RunOutcome,
    ) -> None:
        """Test that composite delegates to all hooks."""
        await composite.on_run_start(run_context)
        await composite.on_run_complete(run_context, run_outcome)

        assert "run_start" in events
        assert "run_complete" in events

    @pytest.mark.asyncio
    async def test_handles_hook_errors(
        self,
        events: list[str],
    ) -> None:
        """Test that composite handles errors in hooks gracefully."""

        class FailingHook(ObservabilityHooks):
            async def on_run_start(self, context: RunContext) -> None:
                raise RuntimeError("Hook failed")

            async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
                pass

            async def on_node_start(self, context: NodeContext) -> None:
                pass

            async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
                pass

            async def on_node_error(
                self,
                context: NodeContext,
                error: str,
                result: NodeResult | None = None,
            ) -> None:
                pass

            async def on_decision_made(self, decision: DecisionData) -> None:
                pass

            async def on_tool_call(
                self,
                tool_name: str,
                args: dict,
                result: str,
                context: NodeContext,
                is_error: bool = False,
                latency_ms: int = 0,
            ) -> None:
                pass

            async def on_llm_call(
                self,
                model: str,
                input_tokens: int,
                output_tokens: int,
                context: NodeContext,
                latency_ms: int = 0,
                cached_tokens: int = 0,
                error: str | None = None,
            ) -> None:
                pass

            async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
                pass

            async def on_retry(self, data: RetryData) -> None:
                pass

        class SuccessHook(ObservabilityHooks):
            def __init__(self, events_list: list[str]) -> None:
                self.events = events_list

            async def on_run_start(self, context: RunContext) -> None:
                self.events.append("success")

            async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
                pass

            async def on_node_start(self, context: NodeContext) -> None:
                pass

            async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
                pass

            async def on_node_error(
                self,
                context: NodeContext,
                error: str,
                result: NodeResult | None = None,
            ) -> None:
                pass

            async def on_decision_made(self, decision: DecisionData) -> None:
                pass

            async def on_tool_call(
                self,
                tool_name: str,
                args: dict,
                result: str,
                context: NodeContext,
                is_error: bool = False,
                latency_ms: int = 0,
            ) -> None:
                pass

            async def on_llm_call(
                self,
                model: str,
                input_tokens: int,
                output_tokens: int,
                context: NodeContext,
                latency_ms: int = 0,
                cached_tokens: int = 0,
                error: str | None = None,
            ) -> None:
                pass

            async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
                pass

            async def on_retry(self, data: RetryData) -> None:
                pass

        composite = CompositeHooks([FailingHook(), SuccessHook(events)])
        run_context = RunContext(run_id="test", goal_id="test")

        await composite.on_run_start(run_context)

        assert "success" in events

    def test_add_hook(self, tracking_hook: ObservabilityHooks) -> None:
        """Test that hooks can be added dynamically."""
        events: list[str] = []

        class AnotherHook(ObservabilityHooks):
            def __init__(self, events_list: list[str]) -> None:
                self.events = events_list

            async def on_run_start(self, context: RunContext) -> None:
                self.events.append("another")

            async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
                pass

            async def on_node_start(self, context: NodeContext) -> None:
                pass

            async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
                pass

            async def on_node_error(
                self,
                context: NodeContext,
                error: str,
                result: NodeResult | None = None,
            ) -> None:
                pass

            async def on_decision_made(self, decision: DecisionData) -> None:
                pass

            async def on_tool_call(
                self,
                tool_name: str,
                args: dict,
                result: str,
                context: NodeContext,
                is_error: bool = False,
                latency_ms: int = 0,
            ) -> None:
                pass

            async def on_llm_call(
                self,
                model: str,
                input_tokens: int,
                output_tokens: int,
                context: NodeContext,
                latency_ms: int = 0,
                cached_tokens: int = 0,
                error: str | None = None,
            ) -> None:
                pass

            async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
                pass

            async def on_retry(self, data: RetryData) -> None:
                pass

        composite = CompositeHooks([tracking_hook])
        composite.add_hook(AnotherHook(events))

        assert len(composite._hooks) == 2


class TestDataClasses:
    """Tests for data classes."""

    def test_run_context_to_dict(self) -> None:
        """Test RunContext serialization."""
        ctx = RunContext(
            run_id="test-run",
            goal_id="test-goal",
            goal_description="Test",
            input_data={"key": "value"},
            trace_id="trace-123",
            execution_id="exec-456",
        )
        d = ctx.to_dict()
        assert d["run_id"] == "test-run"
        assert d["goal_id"] == "test-goal"
        assert "started_at" in d

    def test_node_result_to_dict(self) -> None:
        """Test NodeResult serialization."""
        result = NodeResult(
            node_id="test-node",
            success=True,
            output={"key": "value"},
            tokens_used=100,
            latency_ms=50,
        )
        d = result.to_dict()
        assert d["node_id"] == "test-node"
        assert d["success"] is True
        assert d["tokens_used"] == 100

    def test_decision_data_to_dict(self) -> None:
        """Test DecisionData serialization."""
        decision = DecisionData(
            decision_id="dec-1",
            node_id="node-1",
            intent="Test intent",
            options=[{"id": "a", "description": "Option A"}],
            chosen="a",
            reasoning="Test reasoning",
        )
        d = decision.to_dict()
        assert d["decision_id"] == "dec-1"
        assert len(d["options"]) == 1

    def test_run_outcome_to_dict(self) -> None:
        """Test RunOutcome serialization."""
        outcome = RunOutcome(
            run_id="test-run",
            success=True,
            narrative="Completed",
            total_tokens=500,
            steps_executed=5,
        )
        d = outcome.to_dict()
        assert d["run_id"] == "test-run"
        assert d["success"] is True
        assert d["total_tokens"] == 500
