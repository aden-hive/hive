
# --- Prometheus Metrics ---
TOKEN_USAGE = Counter('hive_token_usage_total', 'Total tokens consumed', ['agent_type', 'model'])
LATENCY = Histogram('hive_node_latency_seconds', 'Latency per agent node', ['node_name'])

# --- SystemMonitor Tool ---
class SystemMonitor:
    def __init__(self, public_key, secret_key, host="http://localhost:3000"):
        self.langfuse = Langfuse(public_key, secret_key, host)
        # Start Prometheus metrics server on 8000
        start_http_server(8000)

    def trace_node(
        self, node_name: str, agent_type: str, input_data: dict
    ) -> object:
        """Creates a trace for an agent's execution step."""
        return self.langfuse.trace(
            name=node_name,
            metadata={"agent_type": agent_type},
            input=input_data
        )

    def log_metrics(
        self,
        agent_type: str,
        model: str,
        tokens: int,
        duration: float,
        node_name: str,
    ) -> None:
        """Updates Prometheus with real-time performance data."""
        TOKEN_USAGE.labels(agent_type=agent_type, model=model).inc(tokens)
        LATENCY.labels(node_name=node_name).observe(duration)

monitor = SystemMonitor("pk-...", "sk-...")
