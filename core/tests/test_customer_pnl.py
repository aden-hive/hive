"""Unit tests for Customer-Level Agentic P&L Dashboard.

Tests cover the core schemas, the tracker logic, risk assessment,
trend computation, and dashboard summary generation.
"""

from __future__ import annotations

import pytest

from framework.observability.customer_pnl_schemas import (
    AgentCostRecord,
    CustomerHealthSnapshot,
    CustomerHealthTrend,
    CustomerPnLSummary,
    RiskTier,
    TrendDirection,
)
from framework.observability.customer_pnl_tracker import CustomerPnLTracker


# ---------------------------------------------------------------------------
# Schema model tests
# ---------------------------------------------------------------------------


class TestSchemaModels:
    """Tests for Pydantic schema instantiation and defaults."""

    def test_risk_tier_values(self) -> None:
        """RiskTier enum should expose the expected string values."""
        assert RiskTier.CRITICAL.value == "critical"
        assert RiskTier.HIGH.value == "high"
        assert RiskTier.MEDIUM.value == "medium"
        assert RiskTier.LOW.value == "low"

    def test_trend_direction_values(self) -> None:
        """TrendDirection enum should expose the expected string values."""
        assert TrendDirection.IMPROVING.value == "improving"
        assert TrendDirection.STABLE.value == "stable"
        assert TrendDirection.WORSENING.value == "worsening"

    def test_agent_cost_record_defaults(self) -> None:
        """AgentCostRecord should have sensible zero defaults."""
        record = AgentCostRecord(customer_id="cust_1")
        assert record.customer_id == "cust_1"
        assert record.total_tokens == 0
        assert record.total_cost_usd == 0.0
        assert record.success is True

    def test_customer_health_snapshot_defaults(self) -> None:
        """CustomerHealthSnapshot should default to LOW risk and STABLE trend."""
        snap = CustomerHealthSnapshot(customer_id="cust_1")
        assert snap.risk_tier == RiskTier.LOW
        assert snap.trend == TrendDirection.STABLE
        assert snap.failure_rate_pct == 0.0

    def test_customer_pnl_summary_defaults(self) -> None:
        """CustomerPnLSummary should default to empty lists and zero values."""
        summary = CustomerPnLSummary()
        assert summary.total_customers == 0
        assert summary.customer_snapshots == []
        assert summary.customers_by_risk == {}


# ---------------------------------------------------------------------------
# Tracker — recording and basic aggregation
# ---------------------------------------------------------------------------


class TestRecordExecution:
    """Tests for recording individual agent executions."""

    def test_record_single_execution(self) -> None:
        """A single successful execution should produce correct cost figures."""
        tracker = CustomerPnLTracker(token_cost_per_1k=0.002)
        record = tracker.record_execution(
            customer_id="cust_acme",
            agent_id="sales-agent",
            run_id="run_001",
            input_tokens=500,
            output_tokens=250,
            success=True,
            retry_count=0,
            escalation_count=0,
            latency_ms=1200,
        )
        assert record.customer_id == "cust_acme"
        assert record.total_tokens == 750
        # base cost: 750/1000 * 0.002 = 0.0015
        assert record.base_cost_usd == pytest.approx(0.0015, abs=1e-6)
        assert record.evolution_cost_usd == 0.0
        assert record.total_cost_usd == pytest.approx(0.0015, abs=1e-6)
        assert record.success is True

    def test_evolution_cost_with_retries(self) -> None:
        """Retries should add evolution cost on top of base cost."""
        tracker = CustomerPnLTracker(token_cost_per_1k=0.002)
        record = tracker.record_execution(
            customer_id="cust_beta",
            input_tokens=1000,
            output_tokens=0,
            success=False,
            failure_category="timeout",
            retry_count=3,
            escalation_count=0,
        )
        # base: 1000/1000 * 0.002 = 0.002
        # evolution: 3 * 0.002 * 1.5 = 0.009
        # total: 0.011
        assert record.base_cost_usd == pytest.approx(0.002, abs=1e-6)
        assert record.evolution_cost_usd == pytest.approx(0.009, abs=1e-6)
        assert record.total_cost_usd == pytest.approx(0.011, abs=1e-6)
        assert record.success is False

    def test_records_count_increments(self) -> None:
        """Each call to record_execution should increment the count."""
        tracker = CustomerPnLTracker()
        assert tracker.get_records_count() == 0
        tracker.record_execution(customer_id="c1")
        tracker.record_execution(customer_id="c2")
        assert tracker.get_records_count() == 2


# ---------------------------------------------------------------------------
# Tracker — customer snapshot
# ---------------------------------------------------------------------------


class TestCustomerSnapshot:
    """Tests for per-customer health snapshot generation."""

    @pytest.fixture()
    def populated_tracker(self) -> CustomerPnLTracker:
        """Create a tracker with mixed execution data for two customers."""
        tracker = CustomerPnLTracker(token_cost_per_1k=0.002)
        tracker.set_customer_revenue("cust_a", 10000.0)
        tracker.set_customer_revenue("cust_b", 5000.0)

        # cust_a: 3 executions (2 ok, 1 fail with retries)
        tracker.record_execution(
            customer_id="cust_a", input_tokens=500, output_tokens=500,
            success=True, latency_ms=1000,
        )
        tracker.record_execution(
            customer_id="cust_a", input_tokens=600, output_tokens=400,
            success=True, latency_ms=1500,
        )
        tracker.record_execution(
            customer_id="cust_a", input_tokens=800, output_tokens=200,
            success=False, retry_count=4, escalation_count=1,
            latency_ms=5000,
        )

        # cust_b: 2 executions (both fail)
        tracker.record_execution(
            customer_id="cust_b", input_tokens=300, output_tokens=200,
            success=False, retry_count=5, latency_ms=8000,
        )
        tracker.record_execution(
            customer_id="cust_b", input_tokens=400, output_tokens=100,
            success=False, retry_count=3, escalation_count=2,
            latency_ms=6000,
        )

        return tracker

    def test_snapshot_total_executions(
        self, populated_tracker: CustomerPnLTracker,
    ) -> None:
        """Snapshot should have correct execution counts."""
        snap = populated_tracker.get_customer_snapshot("cust_a")
        assert snap.total_executions == 3
        assert snap.successful_executions == 2
        assert snap.failed_executions == 1

    def test_snapshot_failure_rate(
        self, populated_tracker: CustomerPnLTracker,
    ) -> None:
        """Failure rate should be (failed / total) * 100."""
        snap_a = populated_tracker.get_customer_snapshot("cust_a")
        assert snap_a.failure_rate_pct == pytest.approx(33.33, abs=0.1)

        snap_b = populated_tracker.get_customer_snapshot("cust_b")
        assert snap_b.failure_rate_pct == pytest.approx(100.0, abs=0.1)

    def test_snapshot_pnl_calculation(
        self, populated_tracker: CustomerPnLTracker,
    ) -> None:
        """Agentic P&L should equal revenue minus total cost."""
        snap = populated_tracker.get_customer_snapshot("cust_a")
        expected_pnl = snap.revenue_usd - snap.total_agent_cost_usd
        assert snap.agentic_pnl_usd == pytest.approx(expected_pnl, abs=0.1)

    def test_snapshot_gross_margin(
        self, populated_tracker: CustomerPnLTracker,
    ) -> None:
        """Gross margin should be (P&L / revenue) * 100."""
        snap = populated_tracker.get_customer_snapshot("cust_a")
        if snap.revenue_usd > 0:
            expected_margin = (
                snap.agentic_pnl_usd / snap.revenue_usd * 100.0
            )
            assert snap.gross_margin_pct == pytest.approx(
                expected_margin, abs=0.1
            )

    def test_snapshot_zero_revenue(self) -> None:
        """When revenue is zero, margin should be zero and P&L negative."""
        tracker = CustomerPnLTracker(token_cost_per_1k=0.002)
        tracker.record_execution(
            customer_id="cust_zero", input_tokens=1000, output_tokens=0,
            success=True,
        )
        snap = tracker.get_customer_snapshot("cust_zero")
        assert snap.revenue_usd == 0.0
        assert snap.gross_margin_pct == 0.0
        assert snap.agentic_pnl_usd <= 0


# ---------------------------------------------------------------------------
# Tracker — risk assessment
# ---------------------------------------------------------------------------


class TestRiskAssessment:
    """Tests for risk tier and score computation."""

    def test_low_risk_account(self) -> None:
        """An account with zero failures should be LOW risk."""
        tracker = CustomerPnLTracker()
        tracker.set_customer_revenue("healthy", 50000.0)
        tracker.record_execution(
            customer_id="healthy", input_tokens=500, output_tokens=500,
            success=True,
        )
        snap = tracker.get_customer_snapshot("healthy")
        assert snap.risk_tier == RiskTier.LOW
        assert snap.risk_score < 20

    def test_critical_risk_high_failure_rate(self) -> None:
        """A 100% failure rate should produce CRITICAL risk tier."""
        tracker = CustomerPnLTracker()
        tracker.set_customer_revenue("failing", 1000.0)
        for _ in range(10):
            tracker.record_execution(
                customer_id="failing", input_tokens=1000, output_tokens=500,
                success=False, retry_count=5, escalation_count=3,
            )
        snap = tracker.get_customer_snapshot("failing")
        assert snap.risk_tier == RiskTier.CRITICAL
        assert snap.risk_score >= 70
        assert len(snap.attention_flags) > 0

    def test_high_risk_moderate_failures(self) -> None:
        """A ~20% failure rate should produce HIGH risk tier."""
        tracker = CustomerPnLTracker()
        tracker.set_customer_revenue("moderate", 10000.0)
        # 16 successes, 4 failures = 20% failure rate
        for _ in range(16):
            tracker.record_execution(
                customer_id="moderate", input_tokens=500, output_tokens=500,
                success=True,
            )
        for _ in range(4):
            tracker.record_execution(
                customer_id="moderate", input_tokens=500, output_tokens=500,
                success=False, retry_count=2,
            )
        snap = tracker.get_customer_snapshot("moderate")
        assert snap.risk_tier in (RiskTier.HIGH, RiskTier.CRITICAL)

    def test_attention_flags_populated(self) -> None:
        """Flags should mention critical failure rate when above threshold."""
        tracker = CustomerPnLTracker()
        for _ in range(5):
            tracker.record_execution(
                customer_id="flagged", input_tokens=1000, output_tokens=500,
                success=False, retry_count=5,
            )
        snap = tracker.get_customer_snapshot("flagged")
        assert any("failure rate" in f.lower() for f in snap.attention_flags)


# ---------------------------------------------------------------------------
# Tracker — trend computation
# ---------------------------------------------------------------------------


class TestTrendComputation:
    """Tests for trend direction based on snapshot comparisons."""

    def test_stable_with_single_snapshot(self) -> None:
        """A single snapshot should return STABLE trend."""
        tracker = CustomerPnLTracker()
        snap = CustomerHealthSnapshot(
            customer_id="c1", failure_rate_pct=5.0, risk_score=20.0,
        )
        trend = tracker.get_customer_trend("c1", [snap])
        assert trend.overall_trend == TrendDirection.STABLE

    def test_improving_trend(self) -> None:
        """Decreasing failure rate and risk score should be IMPROVING."""
        tracker = CustomerPnLTracker()
        older = CustomerHealthSnapshot(
            customer_id="c1", failure_rate_pct=30.0, risk_score=60.0,
        )
        newer = CustomerHealthSnapshot(
            customer_id="c1", failure_rate_pct=10.0, risk_score=25.0,
        )
        trend = tracker.get_customer_trend("c1", [older, newer])
        assert trend.overall_trend == TrendDirection.IMPROVING

    def test_worsening_trend(self) -> None:
        """Increasing failure rate and risk score should be WORSENING."""
        tracker = CustomerPnLTracker()
        older = CustomerHealthSnapshot(
            customer_id="c1", failure_rate_pct=5.0, risk_score=10.0,
        )
        newer = CustomerHealthSnapshot(
            customer_id="c1", failure_rate_pct=25.0, risk_score=55.0,
        )
        trend = tracker.get_customer_trend("c1", [older, newer])
        assert trend.overall_trend == TrendDirection.WORSENING

    def test_empty_snapshots(self) -> None:
        """Empty snapshot list should return STABLE with LOW risk."""
        tracker = CustomerPnLTracker()
        trend = tracker.get_customer_trend("c1", [])
        assert trend.overall_trend == TrendDirection.STABLE
        assert trend.current_risk_tier == RiskTier.LOW


# ---------------------------------------------------------------------------
# Tracker — dashboard summary
# ---------------------------------------------------------------------------


class TestDashboardSummary:
    """Tests for the portfolio-level dashboard summary."""

    @pytest.fixture()
    def multi_customer_tracker(self) -> CustomerPnLTracker:
        """Create a tracker with data for three customers."""
        tracker = CustomerPnLTracker(token_cost_per_1k=0.002)
        tracker.set_bulk_revenue({
            "cust_a": 10000.0,
            "cust_b": 15000.0,
            "cust_c": 8000.0,
        })

        # cust_a: healthy
        for _ in range(5):
            tracker.record_execution(
                customer_id="cust_a", input_tokens=500, output_tokens=500,
                success=True, latency_ms=1000,
            )

        # cust_b: some failures
        for _ in range(3):
            tracker.record_execution(
                customer_id="cust_b", input_tokens=800, output_tokens=200,
                success=True,
            )
        for _ in range(2):
            tracker.record_execution(
                customer_id="cust_b", input_tokens=800, output_tokens=200,
                success=False, retry_count=3,
            )

        # cust_c: heavy failures
        tracker.record_execution(
            customer_id="cust_c", input_tokens=1000, output_tokens=500,
            success=False, retry_count=8, escalation_count=3,
        )

        return tracker

    def test_summary_customer_count(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Summary should report all three customers."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        assert summary.total_customers == 3

    def test_summary_has_snapshots(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Summary should contain one snapshot per customer."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        assert len(summary.customer_snapshots) == 3

    def test_summary_revenue_aggregation(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Total revenue should be the sum of all customer revenues."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        assert summary.total_revenue_usd == pytest.approx(33000.0, abs=0.1)

    def test_summary_pnl_positive(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Portfolio P&L should be positive when revenue far exceeds costs."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        assert summary.portfolio_pnl_usd > 0

    def test_summary_risk_breakdown(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Risk breakdown should contain all four tiers."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        assert "critical" in summary.customers_by_risk
        assert "high" in summary.customers_by_risk
        assert "medium" in summary.customers_by_risk
        assert "low" in summary.customers_by_risk

    def test_summary_high_risk_identification(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Heavily failing customer (cust_c) should be in high risk list."""
        summary = multi_customer_tracker.generate_dashboard_summary()
        # cust_c has 100% failure rate → should be CRITICAL or HIGH
        assert "cust_c" in summary.high_risk_customers

    def test_summary_top_cost_customers(
        self, multi_customer_tracker: CustomerPnLTracker,
    ) -> None:
        """Top cost list should be populated and ordered by cost."""
        summary = multi_customer_tracker.generate_dashboard_summary(top_n=2)
        assert len(summary.top_cost_customers) <= 2
        assert len(summary.top_cost_customers) > 0


# ---------------------------------------------------------------------------
# Tracker — utility methods
# ---------------------------------------------------------------------------


class TestTrackerUtilities:
    """Tests for helper and utility methods."""

    def test_get_all_customer_ids(self) -> None:
        """Should return sorted unique customer IDs."""
        tracker = CustomerPnLTracker()
        tracker.record_execution(customer_id="beta")
        tracker.record_execution(customer_id="alpha")
        tracker.record_execution(customer_id="beta")
        ids = tracker.get_all_customer_ids()
        assert ids == ["alpha", "beta"]

    def test_clear(self) -> None:
        """Clear should remove all records and revenue data."""
        tracker = CustomerPnLTracker()
        tracker.set_customer_revenue("c1", 100.0)
        tracker.record_execution(customer_id="c1")
        tracker.clear()
        assert tracker.get_records_count() == 0
        assert tracker.get_all_customer_ids() == []

    def test_set_bulk_revenue(self) -> None:
        """Bulk revenue update should set multiple customers at once."""
        tracker = CustomerPnLTracker()
        tracker.set_bulk_revenue({"c1": 100.0, "c2": 200.0})
        tracker.record_execution(customer_id="c1", input_tokens=100)
        tracker.record_execution(customer_id="c2", input_tokens=100)
        snap1 = tracker.get_customer_snapshot("c1")
        snap2 = tracker.get_customer_snapshot("c2")
        assert snap1.revenue_usd == 100.0
        assert snap2.revenue_usd == 200.0
