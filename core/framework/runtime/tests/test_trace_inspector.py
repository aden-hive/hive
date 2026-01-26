"""
Tests for TraceInspector.
"""

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from framework.runtime.trace_inspector import (
    ExecutionTrace,
    PerformanceMetrics,
    TraceEvent,
    TraceInspector,
)
from framework.schemas.decision import Decision, DecisionType, Option, Outcome


def test_trace_inspector_creation():
    """Test creating a trace inspector."""
    inspector = TraceInspector()
    assert inspector is not None
    assert inspector._traces == {}


def test_start_trace():
    """Test starting a trace."""
    inspector = TraceInspector()
    
    trace = inspector.start_trace(
        execution_id="exec_123",
        stream_id="stream_1",
        goal_id="goal_1",
        input_data={"test": "data"},
    )
    
    assert trace.execution_id == "exec_123"
    assert trace.stream_id == "stream_1"
    assert trace.goal_id == "goal_1"
    assert trace.input_data == {"test": "data"}
    assert trace.status == "running"
    assert trace in inspector._traces.values()


def test_add_decision():
    """Test adding decisions to a trace."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    decision = Decision(
        id="dec_1",
        node_id="node_1",
        intent="Test intent",
        decision_type=DecisionType.TOOL_SELECTION,
        options=[
            Option(
                id="opt_1",
                description="Option 1",
                action_type="tool_call",
            )
        ],
        chosen_option_id="opt_1",
        reasoning="Test reasoning",
    )
    
    trace.add_decision(decision)
    
    assert len(trace.decisions) == 1
    assert trace.decisions[0].id == "dec_1"
    assert len(trace.events) == 1
    assert trace.events[0].event_type == "decision"
    assert trace.metrics.decisions == 1


def test_record_outcome():
    """Test recording outcomes."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    decision = Decision(
        id="dec_1",
        node_id="node_1",
        intent="Test intent",
        decision_type=DecisionType.TOOL_SELECTION,
        options=[Option(id="opt_1", description="Option 1", action_type="tool_call")],
        chosen_option_id="opt_1",
    )
    trace.add_decision(decision)
    
    outcome = Outcome(
        success=True,
        result={"test": "result"},
        tokens_used=100,
        latency_ms=500,
        summary="Test outcome",
    )
    
    trace.record_outcome("dec_1", outcome)
    
    assert trace.decisions[0].outcome is not None
    assert trace.decisions[0].outcome.success is True
    assert len(trace.events) == 2  # decision + outcome
    assert trace.metrics.max_decision_latency_ms == 500


def test_analyze_trace():
    """Test analyzing a trace."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    # Add some decisions
    for i in range(3):
        decision = Decision(
            id=f"dec_{i}",
            node_id=f"node_{i}",
            intent=f"Intent {i}",
            decision_type=DecisionType.TOOL_SELECTION,
            options=[Option(id="opt_1", description="Option", action_type="tool_call")],
            chosen_option_id="opt_1",
        )
        trace.add_decision(decision)
        
        outcome = Outcome(
            success=i < 2,  # First 2 succeed, last fails
            tokens_used=100,
            latency_ms=500,
        )
        trace.record_outcome(f"dec_{i}", outcome)
    
    trace.complete("completed", {"result": "done"})
    
    analysis = inspector.analyze(trace)
    
    assert analysis["execution_id"] == "exec_123"
    assert analysis["status"] == "completed"
    assert "summary" in analysis
    assert "decisions" in analysis
    assert "performance" in analysis
    assert "cost" in analysis
    assert analysis["decisions"]["total"] == 3
    assert analysis["decisions"]["successful"] == 2
    assert analysis["decisions"]["failed"] == 1


def test_export_import_trace():
    """Test exporting and importing traces."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    decision = Decision(
        id="dec_1",
        node_id="node_1",
        intent="Test",
        decision_type=DecisionType.TOOL_SELECTION,
        options=[Option(id="opt_1", description="Option", action_type="tool_call")],
        chosen_option_id="opt_1",
    )
    trace.add_decision(decision)
    trace.complete("completed")
    
    with TemporaryDirectory() as tmpdir:
        export_path = Path(tmpdir) / "trace.json"
        inspector.export_trace(trace, export_path)
        
        assert export_path.exists()
        
        # Import it
        imported = inspector.import_trace(export_path)
        
        assert imported.execution_id == trace.execution_id
        assert imported.stream_id == trace.stream_id
        assert len(imported.decisions) == 1
        assert imported.status == "completed"


def test_list_traces():
    """Test listing traces."""
    inspector = TraceInspector()
    
    # Create multiple traces
    for i in range(3):
        trace = inspector.start_trace(
            f"exec_{i}",
            f"stream_{i % 2}",  # Alternate streams
            "goal_1",
        )
        trace.complete("completed")
    
    traces = inspector.list_traces()
    assert len(traces) == 3
    
    # Filter by stream
    traces_stream_0 = inspector.list_traces(stream_id="stream_0")
    assert len(traces_stream_0) == 2  # exec_0 and exec_2


def test_performance_metrics():
    """Test performance metrics calculation."""
    metrics = PerformanceMetrics()
    assert metrics.total_duration_ms == 0
    assert metrics.llm_calls == 0
    
    metrics_dict = metrics.to_dict()
    assert "total_duration_ms" in metrics_dict
    assert "llm_calls" in metrics_dict


def test_trace_complete():
    """Test completing a trace."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    assert trace.completed_at is None
    assert trace.status == "running"
    
    trace.complete("completed", {"result": "done"})
    
    assert trace.completed_at is not None
    assert trace.status == "completed"
    assert trace.output_data == {"result": "done"}
    assert trace.metrics.total_duration_ms > 0


def test_state_snapshots():
    """Test capturing state snapshots."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    trace.capture_state_snapshot("checkpoint_1", {"key": "value"})
    
    assert "checkpoint_1" in trace.state_snapshots
    assert trace.state_snapshots["checkpoint_1"]["state"] == {"key": "value"}


def test_llm_call_tracking():
    """Test tracking LLM calls in metrics."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    trace.add_event(
        "llm_call",
        data={"tokens": 1000, "cost_usd": 0.01},
    )
    
    assert trace.metrics.llm_calls == 1
    assert trace.metrics.total_tokens == 1000
    assert trace.metrics.total_cost_usd == 0.01


def test_tool_call_tracking():
    """Test tracking tool calls."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    trace.add_event("tool_call", data={"tool": "search"})
    
    assert trace.metrics.tool_calls == 1


def test_problems_detection():
    """Test problem detection in analysis."""
    inspector = TraceInspector()
    trace = inspector.start_trace("exec_123", "stream_1", "goal_1")
    
    # Add a failed decision
    decision = Decision(
        id="dec_1",
        node_id="node_1",
        intent="Test",
        decision_type=DecisionType.TOOL_SELECTION,
        options=[Option(id="opt_1", description="Option", action_type="tool_call")],
        chosen_option_id="opt_1",
    )
    trace.add_decision(decision)
    trace.record_outcome("dec_1", Outcome(success=False, error="Test error"))
    
    trace.complete("failed")
    
    analysis = inspector.analyze(trace)
    problems = analysis["problems"]
    
    assert len(problems) > 0
    assert any(p["type"] == "failed_decisions" for p in problems)
