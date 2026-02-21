"""FinOps / Cost Guardrails module for Hive agents.

This module provides comprehensive cost monitoring and control for AI agents:

- **Metrics Collection**: Track tokens, costs, burn rates, and tool usage
- **OpenTelemetry Integration**: Export traces and metrics to OTLP-compatible backends
- **Prometheus Exporter**: Expose /metrics endpoint for Prometheus scraping
- **Budget Policies**: Configure thresholds and actions for cost control
- **Runaway Detection**: Detect and prevent runaway agent loops

Quick Start:
    ```python
    from framework.finops import (
        FinOpsCollector,
        FinOpsConfig,
        BudgetPolicy,
        BudgetAction,
        BudgetThreshold,
        start_prometheus_server,
    )

    # Configure
    config = FinOpsConfig.from_env()

    # Create collector
    collector = FinOpsCollector(config)

    # Start Prometheus server
    start_prometheus_server(collector, config)

    # Track a run
    collector.start_run("run-123", agent_id="my-agent")
    collector.record_llm_tokens(
        run_id="run-123",
        node_id="search",
        input_tokens=1000,
        output_tokens=500,
        model="claude-3-5-sonnet-20241022",
    )
    collector.end_run("run-123", success=True)

    # Add budget policies
    from framework.finops import BudgetPolicyEngine, BudgetPolicy, BudgetAction, BudgetThreshold

    engine = BudgetPolicyEngine()
    engine.add_policy(BudgetPolicy(
        name="daily-budget",
        scope="agent",
        scope_id="my-agent",
        max_cost_usd_per_run=1.0,
        thresholds=[
            BudgetThreshold(threshold=50, action=BudgetAction.WARN),
            BudgetThreshold(threshold=75, action=BudgetAction.DEGRADE),
            BudgetThreshold(threshold=100, action=BudgetAction.KILL),
        ],
    ))
    ```

Environment Variables:
    HIVE_FINOPS_ENABLED: Enable/disable FinOps (default: true)
    HIVE_PROMETHEUS_ENABLED: Enable Prometheus exporter (default: true)
    HIVE_PROMETHEUS_PORT: Prometheus metrics port (default: 9090)
    HIVE_PROMETHEUS_HOST: Prometheus metrics host (default: 0.0.0.0)
    HIVE_OTEL_ENABLED: Enable OpenTelemetry export (default: false)
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint URL
    OTEL_SERVICE_NAME: Service name for OTel (default: hive-agent)
    HIVE_RUNAWAY_DETECTION_ENABLED: Enable runaway detection (default: true)
    HIVE_RUNAWAY_FAILURE_THRESHOLD: Consecutive failures for runaway (default: 3)
    HIVE_RUNAWAY_BURN_RATE_MULTIPLIER: Burn rate multiplier for runaway (default: 2.0)

Key Metrics (Prometheus):
    - hive_runs_total: Total runs by agent and status
    - hive_runs_active: Currently active runs
    - hive_tokens_input_total: Input tokens by model/node
    - hive_tokens_output_total: Output tokens by model/node
    - hive_estimated_cost_usd_total: Estimated cost by model
    - hive_burn_rate_tokens_per_min: Current burn rate per run
    - hive_runaway_detected_total: Runaway loop detections
    - hive_budget_alerts_total: Budget policy alerts
    - hive_node_latency_seconds: Node execution latency
    - hive_tool_calls_total: Tool call counts
"""

from __future__ import annotations

from framework.finops.budget import (
    BudgetAction,
    BudgetActionHandler,
    BudgetAlert,
    BudgetExceededError,
    BudgetPolicyEngine,
    get_policy_engine,
    reset_policy_engine,
)
from framework.finops.config import (
    BudgetPolicy,
    BudgetThreshold,
    FinOpsConfig,
)
from framework.finops.metrics import (
    BurnRateSample,
    FinOpsCollector,
    NodeMetrics,
    RunMetrics,
    TokenUsage,
    ToolMetrics,
    finops_context,
    get_collector,
    reset_collector,
)
from framework.finops.otel import (
    get_meter,
    get_tracer,
    init_otel,
    is_otel_available,
    record_budget_alert as otel_record_budget_alert,
    record_run_metrics,
    record_runaway_detection,
    record_token_metrics,
    start_node_span,
    start_run_span,
    start_tool_span,
)
from framework.finops.pricing import (
    MODEL_PRICING,
    ModelPricing,
    estimate_cost,
    get_model_pricing,
)
from framework.finops.prometheus import (
    PrometheusExporter,
    PrometheusMetrics,
    get_metrics,
    get_prometheus_exporter,
    is_prometheus_available,
    reset_prometheus,
    start_prometheus_server,
)

__all__ = [
    "BudgetAction",
    "BudgetActionHandler",
    "BudgetAlert",
    "BudgetExceededError",
    "BudgetPolicy",
    "BudgetPolicyEngine",
    "BudgetThreshold",
    "BurnRateSample",
    "MODEL_PRICING",
    "ModelPricing",
    "NodeMetrics",
    "PrometheusExporter",
    "PrometheusMetrics",
    "RunMetrics",
    "TokenUsage",
    "ToolMetrics",
    "estimate_cost",
    "finops_context",
    "get_collector",
    "get_meter",
    "get_metrics",
    "get_model_pricing",
    "get_policy_engine",
    "get_prometheus_exporter",
    "get_tracer",
    "init_otel",
    "is_otel_available",
    "is_prometheus_available",
    "otel_record_budget_alert",
    "record_run_metrics",
    "record_runaway_detection",
    "record_token_metrics",
    "reset_collector",
    "reset_policy_engine",
    "reset_prometheus",
    "start_node_span",
    "start_prometheus_server",
    "start_run_span",
    "start_tool_span",
]
