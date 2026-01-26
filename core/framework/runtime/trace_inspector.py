"""
Execution Trace Inspector - Comprehensive debugging and observability tool.

Provides detailed inspection of agent executions including:
- Decision timeline visualization
- State inspection at any point
- Cost and performance analysis
- Step-by-step execution replay
- Export/import for offline analysis
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.schemas.decision import Decision, Outcome
from framework.schemas.run import Run, RunStatus

if TYPE_CHECKING:
    from framework.runtime.event_bus import AgentEvent, EventBus
    from framework.runtime.outcome_aggregator import OutcomeAggregator

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    """A single event in the execution trace."""
    timestamp: datetime
    event_type: str  # "decision", "outcome", "state_change", "llm_call", "tool_call"
    stream_id: str
    execution_id: str
    node_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Performance metrics for an execution."""
    total_duration_ms: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    decisions: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_decision_latency_ms: float = 0.0
    max_decision_latency_ms: int = 0
    nodes_executed: set[str] = field(default_factory=set)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_duration_ms": self.total_duration_ms,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "decisions": self.decisions,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "avg_decision_latency_ms": self.avg_decision_latency_ms,
            "max_decision_latency_ms": self.max_decision_latency_ms,
            "nodes_executed": list(self.nodes_executed),
        }


@dataclass
class ExecutionTrace:
    """Complete trace of an execution."""
    execution_id: str
    stream_id: str
    goal_id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    
    # Trace events in chronological order
    events: list[TraceEvent] = field(default_factory=list)
    
    # Decisions made during execution
    decisions: list[Decision] = field(default_factory=list)
    
    # Performance metrics
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    
    # State snapshots at key points
    state_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    def add_event(
        self,
        event_type: str,
        node_id: str | None = None,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to the trace."""
        event = TraceEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            stream_id=self.stream_id,
            execution_id=self.execution_id,
            node_id=node_id,
            data=data or {},
            metadata=metadata or {},
        )
        self.events.append(event)
        
        # Update metrics based on event type
        if event_type == "decision":
            self.metrics.decisions += 1
        elif event_type == "llm_call":
            self.metrics.llm_calls += 1
            if "tokens" in (data or {}):
                self.metrics.total_tokens += data.get("tokens", 0)
            if "cost_usd" in (data or {}):
                self.metrics.total_cost_usd += data.get("cost_usd", 0.0)
        elif event_type == "tool_call":
            self.metrics.tool_calls += 1
        elif event_type == "node_executed" and node_id:
            self.metrics.nodes_executed.add(node_id)
    
    def add_decision(self, decision: Decision) -> None:
        """Add a decision to the trace."""
        self.decisions.append(decision)
        self.add_event(
            event_type="decision",
            node_id=decision.node_id,
            data={
                "decision_id": decision.id,
                "intent": decision.intent,
                "decision_type": decision.decision_type.value,
                "chosen_option_id": decision.chosen_option_id,
            },
        )
    
    def record_outcome(self, decision_id: str, outcome: Outcome) -> None:
        """Record the outcome of a decision."""
        # Find the decision
        for decision in self.decisions:
            if decision.id == decision_id:
                decision.outcome = outcome
                break
        
        # Add outcome event
        self.add_event(
            event_type="outcome",
            data={
                "decision_id": decision_id,
                "success": outcome.success,
                "latency_ms": outcome.latency_ms,
                "tokens_used": outcome.tokens_used,
                "summary": outcome.summary,
            },
        )
        
        # Update metrics
        if outcome.latency_ms > self.metrics.max_decision_latency_ms:
            self.metrics.max_decision_latency_ms = outcome.latency_ms
        
        # Recalculate average
        if self.metrics.decisions > 0:
            total_latency = sum(
                d.outcome.latency_ms 
                for d in self.decisions 
                if d.outcome
            )
            self.metrics.avg_decision_latency_ms = total_latency / self.metrics.decisions
    
    def capture_state_snapshot(self, label: str, state: dict[str, Any]) -> None:
        """Capture a state snapshot at a specific point."""
        self.state_snapshots[label] = {
            "timestamp": datetime.now().isoformat(),
            "state": state.copy(),
        }
    
    def complete(self, status: str, output_data: dict[str, Any] | None = None) -> None:
        """Mark the trace as complete."""
        self.status = status
        self.completed_at = datetime.now()
        if output_data:
            self.output_data = output_data
        
        # Calculate total duration
        if self.completed_at:
            delta = self.completed_at - self.started_at
            self.metrics.total_duration_ms = int(delta.total_seconds() * 1000)
    
    def to_dict(self) -> dict:
        """Convert trace to dictionary for serialization."""
        return {
            "execution_id": self.execution_id,
            "stream_id": self.stream_id,
            "goal_id": self.goal_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type,
                    "node_id": e.node_id,
                    "data": e.data,
                    "metadata": e.metadata,
                }
                for e in self.events
            ],
            "decisions": [d.model_dump() for d in self.decisions],
            "metrics": self.metrics.to_dict(),
            "state_snapshots": self.state_snapshots,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionTrace":
        """Create trace from dictionary."""
        trace = cls(
            execution_id=data["execution_id"],
            stream_id=data["stream_id"],
            goal_id=data["goal_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            status=data.get("status", "unknown"),
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data", {}),
        )
        
        # Restore events
        for event_data in data.get("events", []):
            trace.events.append(TraceEvent(
                timestamp=datetime.fromisoformat(event_data["timestamp"]),
                event_type=event_data["event_type"],
                stream_id=trace.stream_id,
                execution_id=trace.execution_id,
                node_id=event_data.get("node_id"),
                data=event_data.get("data", {}),
                metadata=event_data.get("metadata", {}),
            ))
        
        # Restore decisions
        for decision_data in data.get("decisions", []):
            trace.decisions.append(Decision(**decision_data))
        
        # Restore metrics
        metrics_data = data.get("metrics", {})
        trace.metrics = PerformanceMetrics(
            total_duration_ms=metrics_data.get("total_duration_ms", 0),
            llm_calls=metrics_data.get("llm_calls", 0),
            tool_calls=metrics_data.get("tool_calls", 0),
            decisions=metrics_data.get("decisions", 0),
            total_tokens=metrics_data.get("total_tokens", 0),
            total_cost_usd=metrics_data.get("total_cost_usd", 0.0),
            avg_decision_latency_ms=metrics_data.get("avg_decision_latency_ms", 0.0),
            max_decision_latency_ms=metrics_data.get("max_decision_latency_ms", 0),
            nodes_executed=set(metrics_data.get("nodes_executed", [])),
        )
        
        trace.state_snapshots = data.get("state_snapshots", {})
        
        return trace


class TraceInspector:
    """
    Inspector for analyzing execution traces.
    
    Provides comprehensive debugging capabilities:
    - Timeline visualization
    - Decision analysis
    - Performance profiling
    - Cost analysis
    - State inspection
    - Export/import for offline analysis
    
    Example:
        inspector = TraceInspector()
        
        # Collect trace during execution
        trace = inspector.start_trace(execution_id, stream_id, goal_id)
        
        # ... execution happens ...
        
        # Analyze trace
        analysis = inspector.analyze(trace)
        print(analysis["summary"])
        
        # Export for offline analysis
        inspector.export_trace(trace, "trace.json")
    """
    
    def __init__(self, storage_path: Path | str | None = None):
        """
        Initialize trace inspector.
        
        Args:
            storage_path: Optional path to store traces persistently
        """
        self._traces: dict[str, ExecutionTrace] = {}
        self._storage_path = Path(storage_path) if storage_path else None
        
        if self._storage_path:
            self._storage_path.mkdir(parents=True, exist_ok=True)
    
    def start_trace(
        self,
        execution_id: str,
        stream_id: str,
        goal_id: str,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionTrace:
        """
        Start tracking a new execution.
        
        Args:
            execution_id: Unique execution identifier
            stream_id: Stream identifier
            goal_id: Goal identifier
            input_data: Initial input data
            
        Returns:
            ExecutionTrace instance
        """
        trace = ExecutionTrace(
            execution_id=execution_id,
            stream_id=stream_id,
            goal_id=goal_id,
            started_at=datetime.now(),
            input_data=input_data or {},
        )
        
        self._traces[execution_id] = trace
        logger.debug(f"Started trace for execution {execution_id}")
        
        return trace
    
    def get_trace(self, execution_id: str) -> ExecutionTrace | None:
        """Get trace for an execution."""
        return self._traces.get(execution_id)
    
    def complete_trace(
        self,
        execution_id: str,
        status: str,
        output_data: dict[str, Any] | None = None,
    ) -> None:
        """Mark a trace as complete."""
        trace = self._traces.get(execution_id)
        if trace:
            trace.complete(status, output_data)
            
            # Auto-save if storage path provided
            if self._storage_path:
                self._save_trace(trace)
    
    def analyze(self, trace: ExecutionTrace) -> dict[str, Any]:
        """
        Analyze a trace and provide insights.
        
        Returns:
            Dictionary with analysis results including:
            - summary: High-level summary
            - timeline: Chronological event timeline
            - decisions: Decision analysis
            - performance: Performance insights
            - cost: Cost breakdown
            - problems: Issues detected
            - recommendations: Suggested improvements
        """
        analysis = {
            "execution_id": trace.execution_id,
            "status": trace.status,
            "duration_ms": trace.metrics.total_duration_ms,
            "summary": self._generate_summary(trace),
            "timeline": self._build_timeline(trace),
            "decisions": self._analyze_decisions(trace),
            "performance": self._analyze_performance(trace),
            "cost": self._analyze_cost(trace),
            "problems": self._detect_problems(trace),
            "recommendations": self._generate_recommendations(trace),
        }
        
        return analysis
    
    def _generate_summary(self, trace: ExecutionTrace) -> str:
        """Generate a high-level summary."""
        parts = []
        
        status_emoji = "✓" if trace.status == "completed" else "✗" if trace.status == "failed" else "⏳"
        parts.append(f"{status_emoji} Execution {trace.status}")
        
        # Format duration nicely
        duration_ms = trace.metrics.total_duration_ms
        if duration_ms < 1000:
            duration_str = f"{duration_ms}ms"
        elif duration_ms < 60000:
            duration_str = f"{duration_ms/1000:.1f}s"
        else:
            duration_str = f"{duration_ms/60000:.1f}m"
        parts.append(f"Duration: {duration_str}")
        
        parts.append(f"Decisions: {trace.metrics.decisions}")
        parts.append(f"LLM calls: {trace.metrics.llm_calls}")
        parts.append(f"Tool calls: {trace.metrics.tool_calls}")
        
        if trace.metrics.total_cost_usd > 0:
            parts.append(f"Cost: ${trace.metrics.total_cost_usd:.4f}")
        
        success_rate = (
            sum(1 for d in trace.decisions if d.was_successful) / max(1, len(trace.decisions))
        )
        parts.append(f"Success rate: {success_rate:.1%}")
        
        return " | ".join(parts)
    
    def _build_timeline(self, trace: ExecutionTrace) -> list[dict]:
        """Build chronological timeline of events."""
        timeline = []
        
        for event in trace.events:
            timeline.append({
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "node_id": event.node_id,
                "description": self._describe_event(event),
            })
        
        return timeline
    
    def _describe_event(self, event: TraceEvent) -> str:
        """Generate human-readable description of event."""
        if event.event_type == "decision":
            intent = event.data.get("intent", "unknown")
            return f"Decision: {intent}"
        elif event.event_type == "outcome":
            success = "✓" if event.data.get("success") else "✗"
            return f"Outcome: {success} {event.data.get('summary', '')}"
        elif event.event_type == "llm_call":
            return f"LLM call ({event.data.get('tokens', 0)} tokens)"
        elif event.event_type == "tool_call":
            tool = event.data.get("tool", "unknown")
            return f"Tool: {tool}"
        elif event.event_type == "node_executed":
            return f"Node: {event.node_id}"
        else:
            return f"{event.event_type}"
    
    def _analyze_decisions(self, trace: ExecutionTrace) -> dict[str, Any]:
        """Analyze decisions made during execution."""
        successful = [d for d in trace.decisions if d.was_successful]
        failed = [d for d in trace.decisions if not d.was_successful]
        
        decision_types = {}
        for d in trace.decisions:
            dt = d.decision_type.value
            decision_types[dt] = decision_types.get(dt, 0) + 1
        
        return {
            "total": len(trace.decisions),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / max(1, len(trace.decisions)),
            "by_type": decision_types,
            "failed_decisions": [
                {
                    "id": d.id,
                    "node_id": d.node_id,
                    "intent": d.intent,
                    "reasoning": d.reasoning,
                    "error": d.outcome.error if d.outcome else None,
                }
                for d in failed[:5]  # Top 5 failures
            ],
        }
    
    def _analyze_performance(self, trace: ExecutionTrace) -> dict[str, Any]:
        """Analyze performance characteristics."""
        insights = []
        
        # Check for slow decisions
        slow_decisions = [
            d for d in trace.decisions
            if d.outcome and d.outcome.latency_ms > 5000
        ]
        if slow_decisions:
            insights.append(f"{len(slow_decisions)} decisions took >5s")
        
        # Check for bottlenecks
        if trace.metrics.llm_calls > 0:
            avg_latency = trace.metrics.total_duration_ms / trace.metrics.llm_calls
            if avg_latency > 2000:
                insights.append(f"High LLM latency: {avg_latency:.0f}ms avg")
        
        # Check node execution distribution
        if len(trace.metrics.nodes_executed) > 10:
            insights.append(f"Many nodes executed: {len(trace.metrics.nodes_executed)}")
        
        return {
            "total_duration_ms": trace.metrics.total_duration_ms,
            "avg_decision_latency_ms": trace.metrics.avg_decision_latency_ms,
            "max_decision_latency_ms": trace.metrics.max_decision_latency_ms,
            "nodes_executed": len(trace.metrics.nodes_executed),
            "insights": insights,
        }
    
    def _analyze_cost(self, trace: ExecutionTrace) -> dict[str, Any]:
        """Analyze cost breakdown."""
        if trace.metrics.total_cost_usd == 0:
            return {"total_cost_usd": 0.0, "breakdown": {}}
        
        # Cost per decision
        cost_per_decision = (
            trace.metrics.total_cost_usd / max(1, trace.metrics.decisions)
        )
        
        # Cost per token
        cost_per_token = (
            trace.metrics.total_cost_usd / max(1, trace.metrics.total_tokens)
        )
        
        return {
            "total_cost_usd": trace.metrics.total_cost_usd,
            "cost_per_decision": cost_per_decision,
            "cost_per_token": cost_per_token,
            "total_tokens": trace.metrics.total_tokens,
            "breakdown": {
                "llm_calls": trace.metrics.llm_calls,
                "tokens": trace.metrics.total_tokens,
            },
        }
    
    def _detect_problems(self, trace: ExecutionTrace) -> list[dict]:
        """Detect problems in the execution."""
        problems = []
        
        # Check for failures
        failed_decisions = [d for d in trace.decisions if not d.was_successful]
        if failed_decisions:
            problems.append({
                "severity": "error",
                "type": "failed_decisions",
                "count": len(failed_decisions),
                "description": f"{len(failed_decisions)} decisions failed",
            })
        
        # Check for performance issues
        if trace.metrics.total_duration_ms > 60000:  # > 1 minute
            problems.append({
                "severity": "warning",
                "type": "slow_execution",
                "description": f"Execution took {trace.metrics.total_duration_ms}ms",
            })
        
        # Check for high cost
        if trace.metrics.total_cost_usd > 1.0:
            problems.append({
                "severity": "warning",
                "type": "high_cost",
                "description": f"Execution cost ${trace.metrics.total_cost_usd:.4f}",
            })
        
        # Check for many LLM calls
        if trace.metrics.llm_calls > 50:
            problems.append({
                "severity": "info",
                "type": "many_llm_calls",
                "description": f"{trace.metrics.llm_calls} LLM calls made",
            })
        
        return problems
    
    def _generate_recommendations(self, trace: ExecutionTrace) -> list[str]:
        """Generate recommendations for improvement."""
        recommendations = []
        
        # Check success rate
        success_rate = (
            sum(1 for d in trace.decisions if d.was_successful) / max(1, len(trace.decisions))
        )
        if success_rate < 0.8:
            recommendations.append("Consider improving decision logic - success rate is low")
        
        # Check for retries
        retry_decisions = [
            d for d in trace.decisions
            if d.decision_type.value == "retry_strategy"
        ]
        if len(retry_decisions) > 5:
            recommendations.append("Many retries detected - consider improving error handling")
        
        # Check cost efficiency
        if trace.metrics.total_cost_usd > 0.5 and trace.metrics.decisions < 10:
            recommendations.append("High cost per decision - consider optimizing LLM usage")
        
        # Check latency
        if trace.metrics.avg_decision_latency_ms > 3000:
            recommendations.append("High decision latency - consider caching or optimization")
        
        return recommendations
    
    def export_trace(self, trace: ExecutionTrace, file_path: Path | str) -> None:
        """Export trace to JSON file."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with path.open("w") as f:
            json.dump(trace.to_dict(), f, indent=2, default=str)
        
        logger.info(f"Exported trace to {path}")
    
    def import_trace(self, file_path: Path | str) -> ExecutionTrace:
        """Import trace from JSON file."""
        path = Path(file_path)
        
        with path.open("r") as f:
            data = json.load(f)
        
        trace = ExecutionTrace.from_dict(data)
        self._traces[trace.execution_id] = trace
        
        logger.info(f"Imported trace from {path}")
        return trace
    
    def _save_trace(self, trace: ExecutionTrace) -> None:
        """Save trace to storage."""
        if not self._storage_path:
            return
        
        try:
            file_path = self._storage_path / f"{trace.execution_id}.json"
            self.export_trace(trace, file_path)
            logger.debug(f"Saved trace {trace.execution_id} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save trace {trace.execution_id}: {e}", exc_info=True)
    
    def list_traces(self, stream_id: str | None = None) -> list[dict]:
        """List all traces, optionally filtered by stream."""
        traces = []
        
        for trace in self._traces.values():
            if stream_id and trace.stream_id != stream_id:
                continue
            
            traces.append({
                "execution_id": trace.execution_id,
                "stream_id": trace.stream_id,
                "goal_id": trace.goal_id,
                "status": trace.status,
                "started_at": trace.started_at.isoformat(),
                "duration_ms": trace.metrics.total_duration_ms,
                "decisions": trace.metrics.decisions,
                "cost_usd": trace.metrics.total_cost_usd,
            })
        
        # Sort by started_at descending
        traces.sort(key=lambda x: x["started_at"], reverse=True)
        
        return traces
