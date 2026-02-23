# Customer-Level "Agentic P&L" Dashboard

## Overview

The Customer-Level Agentic P&L Dashboard enables Customer Success (CS) teams to map every LLM dollar to customer revenue. It tracks "Agentic P&Ls" over time, allowing CS teams to proactively identify accounts where agent failure rates (and thus higher "evolution" costs) are impacting gross margins before the monthly bill arrives.

> **Resolves**: [Issue #4041](https://github.com/adenhq/hive/issues/4041) — *Customer-Level "Agentic P&L" Dashboard for CS Teams*

---

## Key Concepts

| Term | Definition |
|------|-----------|
| **Agentic P&L** | Revenue minus total agent costs (LLM + evolution) per customer |
| **Base Cost** | Cost of initial (first-attempt) LLM calls |
| **Evolution Cost** | Additional LLM spend incurred by retries, escalations, and re-executions caused by agent failures |
| **Risk Tier** | Customer classification (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) based on failure rates and margin impact |
| **Customer Health Snapshot** | Point-in-time view of a customer's agent performance and costs |
| **Trend Direction** | Whether a customer's health is `IMPROVING`, `STABLE`, or `WORSENING` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RuntimeLogger (existing)                  │
│    Captures per-node token usage, latency, failures         │
└──────────────────────┬──────────────────────────────────────┘
                       │ feeds into
                       ▼
┌─────────────────────────────────────────────────────────────┐
│               CustomerPnLTracker (new)                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ record_execution()  → AgentCostRecord                │   │
│  │ set_customer_revenue() → External revenue data       │   │
│  │ get_customer_snapshot() → CustomerHealthSnapshot      │   │
│  │ get_customer_trend() → CustomerHealthTrend            │   │
│  │ generate_dashboard_summary() → CustomerPnLSummary    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  Risk Assessment Engine:                                    │
│    • Failure rate scoring (35% weight)                      │
│    • Evolution cost ratio (25% weight)                      │
│    • Margin impact (25% weight)                             │
│    • Retry intensity (15% weight)                           │
└─────────────────────────────────────────────────────────────┘
```

### Module Layout

```
core/framework/observability/
├── __init__.py                    # Updated exports
├── logging.py                     # Existing structured logging
├── customer_pnl_schemas.py        # Pydantic models (NEW)
├── customer_pnl_tracker.py        # Core tracker logic (NEW)
└── README.md                      # Existing observability docs

core/tests/
└── test_customer_pnl.py           # 31 unit tests (NEW)
```

---

## Quick Start

### 1. Record Agent Executions

```python
from framework.observability import CustomerPnLTracker

tracker = CustomerPnLTracker(token_cost_per_1k=0.002)

# Set customer revenue (from CRM/billing)
tracker.set_customer_revenue("cust_acme", 10000.0)
tracker.set_customer_revenue("cust_beta", 15000.0)

# Record executions as they happen
tracker.record_execution(
    customer_id="cust_acme",
    agent_id="sales-agent",
    run_id="20260201T120000_abc12345",
    input_tokens=500,
    output_tokens=250,
    success=True,
    retry_count=0,
    escalation_count=0,
    latency_ms=1200,
)
```

### 2. Get Customer Health Snapshots

```python
snapshot = tracker.get_customer_snapshot(
    customer_id="cust_acme",
    period_start="2026-02-01T00:00:00",
    period_end="2026-02-28T23:59:59",
)

print(f"Customer: {snapshot.customer_id}")
print(f"Agentic P&L: ${snapshot.agentic_pnl_usd:,.2f}")
print(f"Gross Margin: {snapshot.gross_margin_pct:.1f}%")
print(f"Failure Rate: {snapshot.failure_rate_pct:.1f}%")
print(f"Risk Tier: {snapshot.risk_tier.value}")
print(f"Attention Flags: {snapshot.attention_flags}")
```

### 3. Track Trends Over Time

```python
# Compare snapshots from different periods
jan_snapshot = tracker.get_customer_snapshot("cust_acme", "2026-01-01", "2026-01-31")
feb_snapshot = tracker.get_customer_snapshot("cust_acme", "2026-02-01", "2026-02-28")

trend = tracker.get_customer_trend("cust_acme", [jan_snapshot, feb_snapshot])
print(f"Trend: {trend.overall_trend.value}")  # "improving", "stable", or "worsening"
```

### 4. Generate Portfolio Dashboard

```python
summary = tracker.generate_dashboard_summary(
    period_start="2026-02-01T00:00:00",
    period_end="2026-02-28T23:59:59",
    top_n=10,
)

print(f"Total Customers: {summary.total_customers}")
print(f"Portfolio P&L: ${summary.portfolio_pnl_usd:,.2f}")
print(f"Portfolio Margin: {summary.portfolio_margin_pct:.1f}%")
print(f"High-Risk Accounts: {summary.high_risk_customers}")
print(f"Risk Distribution: {summary.customers_by_risk}")
```

---

## Risk Assessment Details

### Thresholds

| Tier | Failure Rate | Risk Score |
|------|-------------|------------|
| **CRITICAL** | ≥ 25% | ≥ 70 |
| **HIGH** | ≥ 15% | ≥ 45 |
| **MEDIUM** | ≥ 5% | ≥ 20 |
| **LOW** | < 5% | < 20 |

### Risk Score Composition

The risk score (0–100) is a weighted composite of four components:

1. **Failure Rate Score** (35%): `min(failure_rate × 2, 100)`
2. **Evolution Cost Ratio** (25%): `min(evolution_cost / total_cost × 100, 100)`
3. **Margin Impact Score** (25%): Penalizes margins below 50%
4. **Retry Intensity Score** (15%): `min(avg_retries × 20, 100)`

### Attention Flags

Flags are generated for:
- Failure rate above CRITICAL or HIGH thresholds
- Evolution costs exceeding 30% of total cost
- Average retries above 3 per execution
- Average escalations above 2 per execution
- Gross margin below 50%

---

## Data Models

### `AgentCostRecord`
Per-execution cost record attributed to a customer. Includes base and evolution costs, failure category, and retry/escalation counts.

### `CustomerHealthSnapshot`
Point-in-time health view with Agentic P&L, failure rates, risk tier, and attention flags.

### `CustomerHealthTrend`
Time-series of snapshots with computed trend direction.

### `CustomerPnLSummary`
Portfolio-level dashboard summary across all customers with risk distribution and top-cost ranking.

---

## Integration with Runtime Logging

The tracker is designed to work alongside the existing `RuntimeLogger` and `RuntimeLogStore`. After each agent execution completes, the run summary data can be fed into the tracker:

```python
from framework.runtime.runtime_log_store import RuntimeLogStore
from framework.observability import CustomerPnLTracker

# Load existing run summaries
store = RuntimeLogStore(base_path=log_dir)
runs = store.list_runs(limit=100)

tracker = CustomerPnLTracker()
for run_summary in runs:
    # Map run to customer (via your customer attribution logic)
    customer_id = map_run_to_customer(run_summary.run_id)
    tracker.record_execution(
        customer_id=customer_id,
        agent_id=run_summary.agent_id,
        run_id=run_summary.run_id,
        input_tokens=run_summary.total_input_tokens,
        output_tokens=run_summary.total_output_tokens,
        success=(run_summary.status == "success"),
    )
```

---

## Testing

Run the test suite:

```bash
cd core
python -m pytest tests/test_customer_pnl.py -v
```

The test suite covers:
- Schema model defaults and enum values (5 tests)
- Execution recording and cost calculations (3 tests)
- Customer snapshot aggregation (5 tests)
- Risk tier assessment (4 tests)
- Trend direction computation (4 tests)
- Dashboard summary generation (7 tests)
- Utility methods (3 tests)

**Total: 31 tests**
