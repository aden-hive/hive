"""Performance tracking for graph execution."""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class PerformanceMetric(str, Enum):
    """Types of performance metrics."""
    EXECUTION_TIME = "execution_time"
    TOKEN_USAGE = "token_usage"
    MEMORY_USAGE = "memory_usage"
    API_CALLS = "api_calls"


@dataclass
class NodePerformance:
    """Performance data for a single node."""
    node_id: str
    node_type: str
    execution_time_ms: float
    tokens_used: Optional[int] = None
    memory_before_mb: Optional[float] = None
    memory_after_mb: Optional[float] = None
    api_calls: int = 0
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class GraphPerformance:
    """Aggregate performance data for a graph execution."""
    graph_id: str
    total_execution_time_ms: float
    total_tokens_used: int
    peak_memory_mb: float
    nodes_performance: List[NodePerformance] = field(default_factory=list)
    node_count: int = 0
    successful_nodes: int = 0
    failed_nodes: int = 0
    
    @property
    def average_node_time_ms(self) -> float:
        """Get average execution time per node."""
        if not self.nodes_performance:
            return 0.0
        return self.total_execution_time_ms / len(self.nodes_performance)
    
    @property
    def success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.node_count == 0:
            return 0.0
        return (self.successful_nodes / self.node_count) * 100


class PerformanceTracker:
    """Tracks performance metrics during graph execution."""
    
    def __init__(self, enable_memory_tracking: bool = False):
        self.enable_memory_tracking = enable_memory_tracking
        self._node_start_times: Dict[str, float] = {}
        self._current_graph: Optional[GraphPerformance] = None
        self._performance_history: List[GraphPerformance] = []
        
    def start_graph(self, graph_id: str) -> None:
        """Start tracking performance for a graph."""
        self._current_graph = GraphPerformance(
            graph_id=graph_id,
            total_execution_time_ms=0.0,
            total_tokens_used=0,
            peak_memory_mb=0.0
        )
        self._node_start_times.clear()
        
    def start_node(self, node_id: str, node_type: str) -> None:
        """Start tracking performance for a node."""
        self._node_start_times[node_id] = time.time()
        
        # Record initial memory if tracking enabled
        memory_before = self._get_memory_usage() if self.enable_memory_tracking else None
        
        node_perf = NodePerformance(
            node_id=node_id,
            node_type=node_type,
            execution_time_ms=0.0,
            memory_before_mb=memory_before
        )
        
        if self._current_graph:
            self._current_graph.nodes_performance.append(node_perf)
            self._current_graph.node_count += 1
    
    def end_node(self, node_id: str, tokens_used: Optional[int] = None, 
                 success: bool = True, error_message: Optional[str] = None) -> None:
        """End tracking for a node."""
        if node_id not in self._node_start_times:
            return
            
        execution_time = (time.time() - self._node_start_times[node_id]) * 1000  # Convert to ms
        
        # Find the node performance record
        if self._current_graph:
            for node_perf in self._current_graph.nodes_performance:
                if node_perf.node_id == node_id:
                    node_perf.execution_time_ms = execution_time
                    node_perf.tokens_used = tokens_used
                    node_perf.success = success
                    node_perf.error_message = error_message
                    
                    # Record memory after if tracking enabled
                    if self.enable_memory_tracking:
                        node_perf.memory_after_mb = self._get_memory_usage()
                    
                    # Update graph totals
                    self._current_graph.total_execution_time_ms += execution_time
                    if tokens_used:
                        self._current_graph.total_tokens_used += tokens_used
                    
                    if success:
                        self._current_graph.successful_nodes += 1
                    else:
                        self._current_graph.failed_nodes += 1
                        
                    break
        
        del self._node_start_times[node_id]
    
    def record_api_call(self, node_id: str) -> None:
        """Record an API call for a node."""
        if self._current_graph:
            for node_perf in self._current_graph.nodes_performance:
                if node_perf.node_id == node_id:
                    node_perf.api_calls += 1
                    break
    
    def end_graph(self) -> GraphPerformance:
        """End tracking for the current graph."""
        if not self._current_graph:
            raise ValueError("No graph currently being tracked")
            
        # Calculate peak memory
        if self.enable_memory_tracking:
            self._current_graph.peak_memory_mb = self._get_memory_usage()
        
        result = self._current_graph
        self._performance_history.append(result)
        self._current_graph = None
        
        return result
    
    def get_performance_summary(self) -> Dict[str, any]:
        """Get summary of performance data."""
        if not self._current_graph:
            return {}
            
        return {
            "graph_id": self._current_graph.graph_id,
            "total_time_ms": self._current_graph.total_execution_time_ms,
            "total_tokens": self._current_graph.total_tokens_used,
            "node_count": self._current_graph.node_count,
            "success_rate": self._current_graph.success_rate,
            "average_node_time_ms": self._current_graph.average_node_time_ms,
            "peak_memory_mb": self._current_graph.peak_memory_mb
        }
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024  # Convert to MB
        except ImportError:
            return 0.0
    
    def get_slowest_nodes(self, top_n: int = 5) -> List[NodePerformance]:
        """Get the slowest nodes by execution time."""
        if not self._current_graph:
            return []
            
        sorted_nodes = sorted(
            self._current_graph.nodes_performance,
            key=lambda x: x.execution_time_ms,
            reverse=True
        )
        return sorted_nodes[:top_n]
