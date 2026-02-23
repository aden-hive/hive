"""Customer-Level Agentic P&L Tracker.

Aggregates runtime log data into per-customer cost and health metrics.
Designed for CS teams to proactively identify accounts where agent failure
rates and evolution costs are impacting gross margins.

The tracker operates on data already captured by the runtime logging system
(``RuntimeLogStore``) and enriches it with customer attribution and cost
calculations.

Typical usage::

    from pathlib import Path
    from framework.observability.customer_pnl_tracker import CustomerPnLTracker

    tracker = CustomerPnLTracker()
    tracker.record_execution(
        customer_id="cust_acme",
        agent_id="sales-agent",
        run_id="20260101T120000_abc12345",
        input_tokens=500,
        output_tokens=250,
        success=True,
        retry_count=0,
        escalation_count=0,
        latency_ms=1200,
    )

    # Generate a full dashboard summary
    summary = tracker.generate_dashboard_summary(
        period_start="2026-01-01T00:00:00",
        period_end="2026-01-31T23:59:59",
    )
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from framework.observability.customer_pnl_schemas import (
    AgentCostRecord,
    CustomerHealthSnapshot,
    CustomerHealthTrend,
    CustomerPnLSummary,
    RiskTier,
    TrendDirection,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cost and threshold constants
# ---------------------------------------------------------------------------
# Approximate cost per 1 000 tokens (USD).  These are conservative defaults;
# callers can override via ``token_cost_per_1k`` in the constructor.
_DEFAULT_TOKEN_COST_PER_1K = 0.002

# Risk-tier thresholds
_CRITICAL_FAILURE_RATE = 25.0  # >= 25 % failure rate → CRITICAL
_HIGH_FAILURE_RATE = 15.0      # >= 15 % failure rate → HIGH
_MEDIUM_FAILURE_RATE = 5.0     # >=  5 % failure rate → MEDIUM

# Evolution-cost multiplier: each retry/escalation costs this multiple of
# the average per-execution base cost.
_EVOLUTION_COST_MULTIPLIER = 1.5


class CustomerPnLTracker:
    """Tracks and aggregates agent costs per customer.

    Thread-safety: not thread-safe by default; callers running in async/
    concurrent contexts should protect the instance with an external lock or
    create one tracker per task.

    Attributes:
        _cost_records: In-memory list of cost records.
        _customer_revenue: Externally provided revenue figures per customer.
        _token_cost_per_1k: USD cost per 1 000 LLM tokens.
    """

    def __init__(
        self,
        token_cost_per_1k: float = _DEFAULT_TOKEN_COST_PER_1K,
    ) -> None:
        """Initialize the tracker.

        Args:
            token_cost_per_1k: USD cost per 1 000 tokens for LLM calls.
        """
        self._cost_records: list[AgentCostRecord] = []
        self._customer_revenue: dict[str, float] = {}
        self._token_cost_per_1k = token_cost_per_1k

    # ------------------------------------------------------------------
    # Revenue management
    # ------------------------------------------------------------------

    def set_customer_revenue(
        self, customer_id: str, revenue_usd: float
    ) -> None:
        """Set the revenue figure for a customer account.

        Revenue is externally sourced (e.g., from a CRM or billing system).
        It is used to compute the Agentic P&L and gross margin.

        Args:
            customer_id: Unique customer identifier.
            revenue_usd: Revenue attributed to this customer for the period.
        """
        self._customer_revenue[customer_id] = revenue_usd

    def set_bulk_revenue(self, revenue_map: dict[str, float]) -> None:
        """Set revenue for multiple customers at once.

        Args:
            revenue_map: Mapping of customer_id → revenue_usd.
        """
        self._customer_revenue.update(revenue_map)

    # ------------------------------------------------------------------
    # Execution recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        customer_id: str,
        agent_id: str = "",
        run_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        success: bool = True,
        failure_category: str = "",
        retry_count: int = 0,
        escalation_count: int = 0,
        latency_ms: int = 0,
        execution_quality: str = "",
        timestamp: str | None = None,
    ) -> AgentCostRecord:
        """Record a single agent execution attributed to a customer.

        Computes base and evolution costs from token counts and retry/
        escalation metrics.

        Args:
            customer_id: Customer that this execution serves.
            agent_id: Agent identifier.
            run_id: Runtime log run ID.
            input_tokens: LLM input tokens consumed.
            output_tokens: LLM output tokens consumed.
            success: Whether the execution succeeded.
            failure_category: Failure label when success is False.
            retry_count: Retries within the execution.
            escalation_count: Escalations within the execution.
            latency_ms: Execution wall-clock time in milliseconds.
            execution_quality: Quality label from RuntimeLogger.
            timestamp: ISO timestamp; defaults to now (UTC).

        Returns:
            The recorded ``AgentCostRecord``.
        """
        if timestamp is None:
            timestamp = datetime.now(UTC).isoformat()

        total_tokens = input_tokens + output_tokens
        base_cost = (total_tokens / 1000.0) * self._token_cost_per_1k

        # Evolution cost: additional spend from retries + escalations.
        evolution_events = retry_count + escalation_count
        evolution_cost = (
            evolution_events * base_cost * _EVOLUTION_COST_MULTIPLIER
            if evolution_events > 0 and base_cost > 0
            else 0.0
        )

        total_cost = base_cost + evolution_cost

        record = AgentCostRecord(
            customer_id=customer_id,
            agent_id=agent_id,
            run_id=run_id,
            timestamp=timestamp,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            base_cost_usd=round(base_cost, 6),
            evolution_cost_usd=round(evolution_cost, 6),
            total_cost_usd=round(total_cost, 6),
            success=success,
            failure_category=failure_category,
            retry_count=retry_count,
            escalation_count=escalation_count,
            latency_ms=latency_ms,
            execution_quality=execution_quality,
        )

        self._cost_records.append(record)
        return record

    # ------------------------------------------------------------------
    # Snapshot generation
    # ------------------------------------------------------------------

    def _get_customer_records(
        self,
        customer_id: str,
        period_start: str | None = None,
        period_end: str | None = None,
    ) -> list[AgentCostRecord]:
        """Return cost records for a customer, optionally filtered by period.

        Args:
            customer_id: Target customer.
            period_start: ISO timestamp lower bound (inclusive).
            period_end: ISO timestamp upper bound (inclusive).

        Returns:
            Filtered list of ``AgentCostRecord`` instances.
        """
        records = [
            r for r in self._cost_records if r.customer_id == customer_id
        ]
        if period_start:
            records = [r for r in records if r.timestamp >= period_start]
        if period_end:
            records = [r for r in records if r.timestamp <= period_end]
        return records

    def get_customer_snapshot(
        self,
        customer_id: str,
        period_start: str = "",
        period_end: str = "",
    ) -> CustomerHealthSnapshot:
        """Compute a point-in-time health snapshot for a customer.

        Args:
            customer_id: Target customer account.
            period_start: ISO timestamp lower bound.
            period_end: ISO timestamp upper bound.

        Returns:
            ``CustomerHealthSnapshot`` with aggregated metrics.
        """
        records = self._get_customer_records(
            customer_id, period_start or None, period_end or None
        )
        revenue = self._customer_revenue.get(customer_id, 0.0)
        return self._build_snapshot(
            customer_id, records, revenue, period_start, period_end
        )

    def _build_snapshot(
        self,
        customer_id: str,
        records: list[AgentCostRecord],
        revenue: float,
        period_start: str,
        period_end: str,
    ) -> CustomerHealthSnapshot:
        """Build a ``CustomerHealthSnapshot`` from raw records.

        Args:
            customer_id: Target customer.
            records: Cost records for the period.
            revenue: Revenue attributable to this customer.
            period_start: Period start (ISO).
            period_end: Period end (ISO).

        Returns:
            Populated ``CustomerHealthSnapshot``.
        """
        total_executions = len(records)
        successful = sum(1 for r in records if r.success)
        failed = total_executions - successful

        total_cost = sum(r.total_cost_usd for r in records)
        base_cost = sum(r.base_cost_usd for r in records)
        evolution_cost = sum(r.evolution_cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)

        failure_rate = (
            (failed / total_executions * 100.0) if total_executions > 0 else 0.0
        )
        avg_retries = (
            sum(r.retry_count for r in records) / total_executions
            if total_executions > 0
            else 0.0
        )
        avg_escalations = (
            sum(r.escalation_count for r in records) / total_executions
            if total_executions > 0
            else 0.0
        )
        avg_latency = (
            sum(r.latency_ms for r in records) / total_executions
            if total_executions > 0
            else 0.0
        )

        pnl = revenue - total_cost
        margin = (pnl / revenue * 100.0) if revenue > 0 else 0.0

        risk_tier, risk_score, flags = self._assess_risk(
            failure_rate, evolution_cost, total_cost, revenue, avg_retries,
            avg_escalations,
        )

        return CustomerHealthSnapshot(
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
            revenue_usd=round(revenue, 2),
            total_agent_cost_usd=round(total_cost, 6),
            base_cost_usd=round(base_cost, 6),
            evolution_cost_usd=round(evolution_cost, 6),
            agentic_pnl_usd=round(pnl, 2),
            gross_margin_pct=round(margin, 2),
            total_executions=total_executions,
            successful_executions=successful,
            failed_executions=failed,
            failure_rate_pct=round(failure_rate, 2),
            avg_retry_count=round(avg_retries, 2),
            avg_escalation_count=round(avg_escalations, 2),
            total_tokens_used=total_tokens,
            avg_latency_ms=round(avg_latency, 2),
            risk_tier=risk_tier,
            risk_score=round(risk_score, 2),
            attention_flags=flags,
            trend=TrendDirection.STABLE,
        )

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    def _assess_risk(
        self,
        failure_rate: float,
        evolution_cost: float,
        total_cost: float,
        revenue: float,
        avg_retries: float,
        avg_escalations: float,
    ) -> tuple[RiskTier, float, list[str]]:
        """Determine risk tier, score, and attention flags.

        The risk score is a weighted composite of failure rate, evolution-cost
        ratio, and retry/escalation intensity.  It ranges from 0 (healthiest)
        to 100 (most at-risk).

        Args:
            failure_rate: Percentage of failed executions.
            evolution_cost: Total evolution cost in USD.
            total_cost: Total agent cost in USD.
            revenue: Customer revenue in USD.
            avg_retries: Average retries per execution.
            avg_escalations: Average escalations per execution.

        Returns:
            Tuple of (risk_tier, risk_score, attention_flags).
        """
        flags: list[str] = []

        # --- component scores (each 0-100) ---
        failure_score = min(failure_rate * 2.0, 100.0)

        evolution_ratio = (
            (evolution_cost / total_cost * 100.0)
            if total_cost > 0
            else 0.0
        )
        evolution_score = min(evolution_ratio, 100.0)

        margin_score = 0.0
        if revenue > 0:
            margin = (revenue - total_cost) / revenue * 100.0
            if margin < 50:
                margin_score = (50 - margin) * 2.0
            margin_score = min(margin_score, 100.0)

        retry_score = min(avg_retries * 20.0, 100.0)

        # Composite (weighted)
        risk_score = (
            failure_score * 0.35
            + evolution_score * 0.25
            + margin_score * 0.25
            + retry_score * 0.15
        )

        # --- flags ---
        if failure_rate >= _CRITICAL_FAILURE_RATE:
            flags.append(
                f"Critical failure rate: {failure_rate:.1f}% "
                f"(threshold: {_CRITICAL_FAILURE_RATE}%)"
            )
        elif failure_rate >= _HIGH_FAILURE_RATE:
            flags.append(
                f"High failure rate: {failure_rate:.1f}% "
                f"(threshold: {_HIGH_FAILURE_RATE}%)"
            )

        if evolution_ratio > 30:
            flags.append(
                f"Evolution costs are {evolution_ratio:.1f}% of total cost"
            )

        if avg_retries > 3:
            flags.append(f"Excessive avg retries: {avg_retries:.1f}")

        if avg_escalations > 2:
            flags.append(f"Excessive avg escalations: {avg_escalations:.1f}")

        if revenue > 0 and (revenue - total_cost) / revenue < 0.5:
            flags.append("Gross margin below 50%")

        # --- tier ---
        if failure_rate >= _CRITICAL_FAILURE_RATE or risk_score >= 70:
            tier = RiskTier.CRITICAL
        elif failure_rate >= _HIGH_FAILURE_RATE or risk_score >= 45:
            tier = RiskTier.HIGH
        elif failure_rate >= _MEDIUM_FAILURE_RATE or risk_score >= 20:
            tier = RiskTier.MEDIUM
        else:
            tier = RiskTier.LOW

        return tier, risk_score, flags

    # ------------------------------------------------------------------
    # Trend computation
    # ------------------------------------------------------------------

    def _compute_trend(
        self,
        current: CustomerHealthSnapshot,
        previous: CustomerHealthSnapshot | None,
    ) -> TrendDirection:
        """Compare two snapshots to determine trend direction.

        The heuristic compares failure rate and risk score: if both
        improve (or stay equal), the trend is IMPROVING; if both worsen,
        WORSENING; otherwise STABLE.

        Args:
            current: The most recent snapshot.
            previous: The prior-period snapshot (may be None).

        Returns:
            ``TrendDirection`` enum value.
        """
        if previous is None:
            return TrendDirection.STABLE

        failure_delta = current.failure_rate_pct - previous.failure_rate_pct
        risk_delta = current.risk_score - previous.risk_score

        if failure_delta < -1 and risk_delta < -1:
            return TrendDirection.IMPROVING
        if failure_delta > 1 and risk_delta > 1:
            return TrendDirection.WORSENING
        return TrendDirection.STABLE

    def get_customer_trend(
        self,
        customer_id: str,
        period_snapshots: list[CustomerHealthSnapshot] | None = None,
    ) -> CustomerHealthTrend:
        """Build a trend object from ordered snapshots.

        Args:
            customer_id: Target customer.
            period_snapshots: Pre-computed snapshots in chronological order.
                If ``None``, returns an empty trend.

        Returns:
            ``CustomerHealthTrend`` with overall direction.
        """
        snapshots = period_snapshots or []
        if not snapshots:
            return CustomerHealthTrend(customer_id=customer_id)

        current = snapshots[-1]
        previous = snapshots[-2] if len(snapshots) >= 2 else None
        overall_trend = self._compute_trend(current, previous)

        return CustomerHealthTrend(
            customer_id=customer_id,
            snapshots=snapshots,
            current_risk_tier=current.risk_tier,
            overall_trend=overall_trend,
        )

    # ------------------------------------------------------------------
    # Dashboard summary
    # ------------------------------------------------------------------

    def generate_dashboard_summary(
        self,
        period_start: str = "",
        period_end: str = "",
        top_n: int = 10,
    ) -> CustomerPnLSummary:
        """Generate the top-level P&L dashboard summary.

        Aggregates all customer snapshots into a portfolio view.

        Args:
            period_start: ISO start of reporting period.
            period_end: ISO end of reporting period.
            top_n: Number of top-cost customers to include.

        Returns:
            ``CustomerPnLSummary`` with portfolio-level metrics.
        """
        customer_ids = sorted(
            {r.customer_id for r in self._cost_records}
        )

        snapshots: list[CustomerHealthSnapshot] = []
        for cid in customer_ids:
            snap = self.get_customer_snapshot(cid, period_start, period_end)
            snapshots.append(snap)

        total_revenue = sum(s.revenue_usd for s in snapshots)
        total_cost = sum(s.total_agent_cost_usd for s in snapshots)
        total_evolution = sum(s.evolution_cost_usd for s in snapshots)
        portfolio_pnl = total_revenue - total_cost
        portfolio_margin = (
            (portfolio_pnl / total_revenue * 100.0)
            if total_revenue > 0
            else 0.0
        )

        risk_counts: dict[str, int] = {
            RiskTier.CRITICAL.value: 0,
            RiskTier.HIGH.value: 0,
            RiskTier.MEDIUM.value: 0,
            RiskTier.LOW.value: 0,
        }
        high_risk_ids: list[str] = []
        for snap in snapshots:
            risk_counts[snap.risk_tier.value] += 1
            if snap.risk_tier in (RiskTier.CRITICAL, RiskTier.HIGH):
                high_risk_ids.append(snap.customer_id)

        avg_failure = (
            sum(s.failure_rate_pct for s in snapshots) / len(snapshots)
            if snapshots
            else 0.0
        )

        # Top-cost customers
        sorted_by_cost = sorted(
            snapshots, key=lambda s: s.total_agent_cost_usd, reverse=True
        )
        top_cost_ids = [s.customer_id for s in sorted_by_cost[:top_n]]

        return CustomerPnLSummary(
            period_start=period_start,
            period_end=period_end,
            total_customers=len(customer_ids),
            total_revenue_usd=round(total_revenue, 2),
            total_agent_cost_usd=round(total_cost, 6),
            total_evolution_cost_usd=round(total_evolution, 6),
            portfolio_pnl_usd=round(portfolio_pnl, 2),
            portfolio_margin_pct=round(portfolio_margin, 2),
            customers_by_risk=risk_counts,
            high_risk_customers=high_risk_ids,
            avg_failure_rate_pct=round(avg_failure, 2),
            top_cost_customers=top_cost_ids,
            customer_snapshots=snapshots,
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_all_customer_ids(self) -> list[str]:
        """Return sorted list of all customer IDs with recorded executions.

        Returns:
            Sorted list of unique customer identifiers.
        """
        return sorted({r.customer_id for r in self._cost_records})

    def get_records_count(self) -> int:
        """Return total number of recorded cost records.

        Returns:
            Integer count of records.
        """
        return len(self._cost_records)

    def clear(self) -> None:
        """Clear all recorded data and revenue entries."""
        self._cost_records.clear()
        self._customer_revenue.clear()
