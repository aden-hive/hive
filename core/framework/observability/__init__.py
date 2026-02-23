"""
Observability module for automatic trace correlation and structured logging.

This module provides zero-friction observability:
- Automatic trace context propagation via ContextVar
- Structured JSON logging for production
- Human-readable logging for development
- No manual ID passing required
- Customer-level Agentic P&L tracking for CS teams
"""

from framework.observability.customer_pnl_schemas import (
    AgentCostRecord,
    CustomerHealthSnapshot,
    CustomerHealthTrend,
    CustomerPnLSummary,
    RiskTier,
    TrendDirection,
)
from framework.observability.customer_pnl_tracker import CustomerPnLTracker
from framework.observability.logging import (
    clear_trace_context,
    configure_logging,
    get_trace_context,
    set_trace_context,
)

__all__ = [
    "configure_logging",
    "get_trace_context",
    "set_trace_context",
    "clear_trace_context",
    # Customer P&L
    "CustomerPnLTracker",
    "AgentCostRecord",
    "CustomerHealthSnapshot",
    "CustomerHealthTrend",
    "CustomerPnLSummary",
    "RiskTier",
    "TrendDirection",
]

