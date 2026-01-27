"""Tests for performance tracking."""

import pytest
import time
from framework.graph.performance_tracker import PerformanceTracker, GraphPerformance


class TestPerformanceTracker:
    def test_basic_tracking(self):
        """Test basic performance tracking functionality."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("test_graph")
        tracker.start_node("node1", "llm_generate")
        
        # Simulate execution time
        time.sleep(0.01)
        
        tracker.end_node("node1", tokens_used=100)
        performance = tracker.end_graph()
        
        assert performance.graph_id == "test_graph"
        assert performance.node_count == 1
        assert performance.successful_nodes == 1
        assert performance.total_tokens_used == 100
        assert performance.total_execution_time_ms > 0

    def test_multiple_nodes(self):
        """Test tracking multiple nodes."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("multi_node_graph")
        
        for i in range(3):
            tracker.start_node(f"node_{i}", "function")
            time.sleep(0.005)
            tracker.end_node(f"node_{i}")
        
        performance = tracker.end_graph()
        
        assert performance.node_count == 3
        assert performance.successful_nodes == 3
        assert len(performance.nodes_performance) == 3

    def test_failed_node(self):
        """Test tracking failed nodes."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("failed_graph")
        tracker.start_node("failed_node", "llm_tool_use")
        tracker.end_node("failed_node", success=False, error_message="Test error")
        performance = tracker.end_graph()
        
        assert performance.failed_nodes == 1
        assert performance.successful_nodes == 0
        assert performance.success_rate == 0.0

    def test_performance_summary(self):
        """Test performance summary generation."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("summary_graph")
        tracker.start_node("summary_node", "router")
        tracker.end_node("summary_node", tokens_used=50)
        performance = tracker.end_graph()
        
        summary = performance.get_performance_summary()
        assert "graph_id" in summary
        assert "total_time_ms" in summary
        assert "success_rate" in summary

    def test_slowest_nodes(self):
        """Test identifying slowest nodes."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("slow_graph")
        
        # Create nodes with different execution times
        tracker.start_node("fast_node", "function")
        time.sleep(0.001)
        tracker.end_node("fast_node")
        
        tracker.start_node("slow_node", "llm_generate") 
        time.sleep(0.01)
        tracker.end_node("slow_node")
        
        performance = tracker.end_graph()
        slowest = performance.get_slowest_nodes(top_n=1)
        
        assert len(slowest) == 1
        assert slowest[0].node_id == "slow_node"

    def test_api_call_tracking(self):
        """Test recording API calls."""
        tracker = PerformanceTracker()
        
        tracker.start_graph("api_graph")
        tracker.start_node("api_node", "web_search")
        tracker.record_api_call("api_node")
        tracker.record_api_call("api_node")
        tracker.end_node("api_node")
        performance = tracker.end_graph()
        
        node_perf = performance.nodes_performance[0]
        assert node_perf.api_calls == 2
        assert node_perf.node_id == "api_node"

    def test_memory_tracking_disabled(self):
        """Test memory tracking when disabled."""
        tracker = PerformanceTracker(enable_memory_tracking=False)
        
        tracker.start_graph("memory_graph")
        tracker.start_node("memory_node", "function")
        tracker.end_node("memory_node")
        performance = tracker.end_graph()
        
        node_perf = performance.nodes_performance[0]
        assert node_perf.memory_before_mb is None
        assert node_perf.memory_after_mb is None

    def test_graph_methods_without_start(self):
        """Test methods called without starting graph."""
        tracker = PerformanceTracker()
        
        # Should not raise errors
        tracker.end_node("nonexistent_node")
        tracker.record_api_call("nonexistent_node")
        
        # end_graph should raise ValueError
        with pytest.raises(ValueError):
            tracker.end_graph()
