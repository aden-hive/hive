"""Metrics collection with Prometheus."""

from prometheus_client import Counter, Histogram, Gauge, Info, start_http_server
from typing import Dict, Any
import time


class MetricsCollector:
    """Prometheus metrics collector."""

    def __init__(self):
        # Agent execution metrics
        self.agent_execution_duration = Histogram(
            'agent_execution_duration_seconds',
            'Agent execution duration in seconds',
            ['agent_name', 'status']
        )

        self.agent_execution_total = Counter(
            'agent_execution_total',
            'Total agent executions',
            ['agent_name', 'status']
        )

        # Node execution metrics
        self.node_execution_duration = Histogram(
            'node_execution_duration_seconds',
            'Node execution duration in seconds',
            ['node_type', 'status']
        )

        self.node_failure_total = Counter(
            'node_failure_total',
            'Total node failures',
            ['node_type', 'error_type']
        )

        # LLM metrics
        self.llm_request_duration = Histogram(
            'llm_request_duration_seconds',
            'LLM request duration in seconds',
            ['llm_provider', 'model']
        )

        self.llm_request_tokens = Counter(
            'llm_request_tokens_total',
            'Total LLM request tokens',
            ['llm_provider', 'model']
        )

        self.llm_response_tokens = Counter(
            'llm_response_tokens_total',
            'Total LLM response tokens',
            ['llm_provider', 'model']
        )

        self.llm_cost_total = Counter(
            'llm_cost_total',
            'Total LLM cost in dollars',
            ['llm_provider', 'model']
        )

        # HTTP metrics
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )

        self.http_request_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint']
        )

        # System metrics
        self.active_agents = Gauge(
            'active_agents',
            'Number of currently active agents'
        )

        self.cache_hit_ratio = Gauge(
            'cache_hit_ratio',
            'Cache hit ratio',
            ['cache_type']
        )

    def record_agent_execution(
        self,
        agent_name: str,
        status: str,
        duration: float
    ):
        """Record agent execution metric."""
        self.agent_execution_duration.labels(
            agent_name=agent_name,
            status=status
        ).observe(duration)
        self.agent_execution_total.labels(
            agent_name=agent_name,
            status=status
        ).inc()

    def record_node_execution(
        self,
        node_type: str,
        status: str,
        duration: float
    ):
        """Record node execution metric."""
        self.node_execution_duration.labels(
            node_type=node_type,
            status=status
        ).observe(duration)

    def record_llm_request(
        self,
        provider: str,
        model: str,
        duration: float,
        request_tokens: int,
        response_tokens: int,
        cost: float
    ):
        """Record LLM request metrics."""
        self.llm_request_duration.labels(
            llm_provider=provider,
            model=model
        ).observe(duration)
        self.llm_request_tokens.labels(
            llm_provider=provider,
            model=model
        ).inc(request_tokens)
        self.llm_response_tokens.labels(
            llm_provider=provider,
            model=model
        ).inc(response_tokens)
        self.llm_cost_total.labels(
            llm_provider=provider,
            model=model
        ).inc(cost)

    def start_metrics_server(self, port: int = 9090):
        """Start Prometheus metrics server."""
        start_http_server(port)


# Global metrics collector instance
metrics = MetricsCollector()
