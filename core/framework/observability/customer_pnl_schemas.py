"""Pydantic models for Customer-Level Agentic P&L tracking.

These models support the "Customer Health" dashboard that maps LLM costs
to customer revenue, tracks failure rates, and surfaces high-risk accounts
for CS teams.

Key Concepts:
    - **Agentic P&L**: Revenue minus total agent costs (LLM + evolution) per
      customer, measured over a configurable time window.
    - **Evolution costs**: Additional LLM spend incurred by retries, escalations,
      and re-executions caused by agent failures.
    - **Risk tier**: Derived from failure rate and margin-impact thresholds.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    """Customer risk classification for CS prioritization.

    Tiers are assigned based on agent failure rates and margin impact:
        - CRITICAL: Failure rate >= critical threshold, high margin erosion.
        - HIGH: Failure rate >= high threshold or significant cost overruns.
        - MEDIUM: Moderate failure rates or rising evolution costs.
        - LOW: Healthy account with minimal agent issues.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TrendDirection(str, Enum):
    """Directional trend indicator for time-series metrics.

    Used by CS teams to identify improving vs. worsening accounts.
    """

    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


class AgentCostRecord(BaseModel):
    """Cost breakdown for a single agent execution attributed to a customer.

    Attributes:
        customer_id: Unique identifier for the customer account.
        agent_id: Identifier of the agent that ran.
        run_id: Runtime log run ID for traceability.
        timestamp: When the execution occurred (ISO format).
        input_tokens: LLM input tokens consumed.
        output_tokens: LLM output tokens consumed.
        total_tokens: Sum of input and output tokens.
        base_cost_usd: Cost of the initial (first-attempt) LLM calls.
        evolution_cost_usd: Additional cost from retries, escalations, and
            re-executions triggered by failures.
        total_cost_usd: base_cost_usd + evolution_cost_usd.
        success: Whether the execution completed successfully.
        failure_category: High-level failure reason if success is False.
        retry_count: Number of retries within the execution.
        escalation_count: Number of escalations within the execution.
        latency_ms: Wall-clock duration of execution in milliseconds.
        execution_quality: Quality label assigned by the runtime logger.
    """

    customer_id: str
    agent_id: str = ""
    run_id: str = ""
    timestamp: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    base_cost_usd: float = 0.0
    evolution_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    success: bool = True
    failure_category: str = ""
    retry_count: int = 0
    escalation_count: int = 0
    latency_ms: int = 0
    execution_quality: str = ""


class CustomerHealthSnapshot(BaseModel):
    """Point-in-time health view for a single customer account.

    Provides the core "Agentic P&L" metrics that CS teams use to assess
    customer health and prioritize interventions.

    Attributes:
        customer_id: Unique customer identifier.
        period_start: Start of the measurement window (ISO format).
        period_end: End of the measurement window (ISO format).
        revenue_usd: Customer revenue during the period (externally provided).
        total_agent_cost_usd: All agent costs attributed to this customer.
        base_cost_usd: Cost of initial (successful) LLM calls.
        evolution_cost_usd: Cost of retries, escalations, and re-runs.
        agentic_pnl_usd: revenue_usd - total_agent_cost_usd.
        gross_margin_pct: (agentic_pnl_usd / revenue_usd) * 100 if revenue > 0.
        total_executions: Number of agent executions for this customer.
        successful_executions: Executions that completed successfully.
        failed_executions: Executions that failed.
        failure_rate_pct: (failed / total) * 100 if total > 0.
        avg_retry_count: Average retries per execution.
        avg_escalation_count: Average escalations per execution.
        total_tokens_used: Sum of all tokens consumed.
        avg_latency_ms: Average execution latency in milliseconds.
        risk_tier: Computed risk classification for CS prioritization.
        risk_score: Numeric score (0-100) combining failure rate and cost impact.
        attention_flags: List of specific issues requiring attention.
        trend: Direction of health change relative to previous period.
    """

    customer_id: str
    period_start: str = ""
    period_end: str = ""
    revenue_usd: float = 0.0
    total_agent_cost_usd: float = 0.0
    base_cost_usd: float = 0.0
    evolution_cost_usd: float = 0.0
    agentic_pnl_usd: float = 0.0
    gross_margin_pct: float = 0.0
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    failure_rate_pct: float = 0.0
    avg_retry_count: float = 0.0
    avg_escalation_count: float = 0.0
    total_tokens_used: int = 0
    avg_latency_ms: float = 0.0
    risk_tier: RiskTier = RiskTier.LOW
    risk_score: float = 0.0
    attention_flags: list[str] = Field(default_factory=list)
    trend: TrendDirection = TrendDirection.STABLE


class CustomerHealthTrend(BaseModel):
    """Time-series health data for a single customer.

    Allows CS teams to visualize trends and spot improving or worsening
    accounts over multiple periods.

    Attributes:
        customer_id: Unique customer identifier.
        snapshots: Ordered list of periodic health snapshots (oldest first).
        current_risk_tier: Most recent risk classification.
        overall_trend: Aggregate trend direction across the series.
    """

    customer_id: str
    snapshots: list[CustomerHealthSnapshot] = Field(default_factory=list)
    current_risk_tier: RiskTier = RiskTier.LOW
    overall_trend: TrendDirection = TrendDirection.STABLE


class CustomerPnLSummary(BaseModel):
    """Aggregate P&L dashboard summary across all customers.

    Top-level view for CS leads showing portfolio health, high-risk
    accounts, and overall P&L metrics.

    Attributes:
        period_start: Start of the reporting period (ISO format).
        period_end: End of the reporting period (ISO format).
        total_customers: Number of active customer accounts.
        total_revenue_usd: Aggregate revenue across all customers.
        total_agent_cost_usd: Aggregate agent costs across all customers.
        total_evolution_cost_usd: Aggregate evolution costs.
        portfolio_pnl_usd: Total revenue minus total agent costs.
        portfolio_margin_pct: Portfolio-level gross margin percentage.
        customers_by_risk: Count of customers in each risk tier.
        high_risk_customers: List of IDs for accounts in HIGH or CRITICAL tier.
        avg_failure_rate_pct: Average failure rate across all customers.
        top_cost_customers: Customer IDs ranked by total agent cost (descending).
        customer_snapshots: Detailed per-customer health snapshots.
    """

    period_start: str = ""
    period_end: str = ""
    total_customers: int = 0
    total_revenue_usd: float = 0.0
    total_agent_cost_usd: float = 0.0
    total_evolution_cost_usd: float = 0.0
    portfolio_pnl_usd: float = 0.0
    portfolio_margin_pct: float = 0.0
    customers_by_risk: dict[str, int] = Field(default_factory=dict)
    high_risk_customers: list[str] = Field(default_factory=list)
    avg_failure_rate_pct: float = 0.0
    top_cost_customers: list[str] = Field(default_factory=list)
    customer_snapshots: list[CustomerHealthSnapshot] = Field(
        default_factory=list
    )
