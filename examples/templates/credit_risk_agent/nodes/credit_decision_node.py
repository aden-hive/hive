"""
Credit Decision Node

Evaluates SME credit applications using a deterministic, explainable
scorecard calibrated for LATAM SME lending.

Outputs:
- credit_score (0–100)
- risk_level
- probability_of_default (range)
- decision
- score_breakdown
"""

from framework.graph import Node, NodeResult


credit_decision_node = Node(
    id="credit_decision",
    name="Credit Decision",
    description="Applies a deterministic scorecard to issue a credit decision",
    client_facing=True,
)


@credit_decision_node.run
def run(input_data: dict, context: dict) -> NodeResult:
    """
    Expected input_data:
    {
        "monthly_cash_flow": float,
        "existing_debt": float,
        "dscr": float,
        "years_in_operation": int,
        "data_sources": list[str],
        "past_defaults": bool
    }
    """

    # -------------------------
    # Input extraction
    # -------------------------
    monthly_cash_flow = input_data["monthly_cash_flow"]
    existing_debt = input_data["existing_debt"]
    dscr = input_data["dscr"]
    years_in_operation = input_data["years_in_operation"]
    data_sources = set(input_data.get("data_sources", []))
    past_defaults = input_data["past_defaults"]

    score = 0

    # ======================================================
    # 1. Repayment Capacity (DSCR) — max 40 pts
    # ======================================================
    if dscr >= 1.5:
        repayment_points = 40
    elif dscr >= 1.3:
        repayment_points = 32
    elif dscr >= 1.1:
        repayment_points = 24
    elif dscr >= 1.0:
        repayment_points = 12
    else:
        repayment_points = 0

    score += repayment_points

    # ======================================================
    # 2. Business Stability (Years in Operation) — max 20 pts
    # ======================================================
    if years_in_operation >= 5:
        stability_points = 20
    elif years_in_operation >= 3:
        stability_points = 15
    elif years_in_operation >= 1:
        stability_points = 8
    else:
        stability_points = 0

    score += stability_points

    # ======================================================
    # 3. Leverage (Debt / Monthly Cash Flow) — max 15 pts
    # LATAM-calibrated thresholds
    # ======================================================
    if monthly_cash_flow > 0:
        debt_months = existing_debt / monthly_cash_flow
    else:
        debt_months = float("inf")

    if monthly_cash_flow <= 0:
        leverage_points = 0
    elif debt_months < 12:
        leverage_points = 15
    elif debt_months <= 18:
        leverage_points = 10
    else:
        leverage_points = 5

    score += leverage_points

    # ======================================================
    # 4. Data Quality — max 15 pts
    # ======================================================
    if {"bank_statements", "pos_sales", "utility_payments"}.issubset(data_sources):
        data_quality_points = 15
    elif {"bank_statements", "pos_sales"}.issubset(data_sources):
        data_quality_points = 12
    elif "bank_statements" in data_sources:
        data_quality_points = 8
    elif len(data_sources) > 0:
        data_quality_points = 4
    else:
        data_quality_points = 0

    score += data_quality_points

    data_quality_assessment = {
        "sources_provided": list(data_sources),
        "points": data_quality_points,
    }

    # ======================================================
    # 5. Credit History — max 10 pts
    # ======================================================
    history_points = 10 if not past_defaults else 0
    score += history_points

    # ======================================================
    # Score Breakdown
    # ======================================================
    score_breakdown = {
        "repayment_capacity": repayment_points,
        "business_stability": stability_points,
        "leverage": leverage_points,
        "data_quality": data_quality_points,
        "credit_history": history_points,
    }

    # ======================================================
    # Decision Logic
    # ======================================================
    if dscr < 1.0:
        decision = "Reject"
        risk_level = "High"
        pd_range = ">15%"
    elif score >= 80:
        decision = "Approve"
        risk_level = "Low"
        pd_range = "1–3%"
    elif score >= 65:
        decision = "Conditional Approval"
        risk_level = "Medium"
        pd_range = "4–8%"
    else:
        decision = "Reject"
        risk_level = "High"
        pd_range = ">15%"

    # ======================================================
    # Output
    # ======================================================
    return NodeResult(
        success=True,
        output={
            "credit_score": score,
            "risk_level": risk_level,
            "probability_of_default": pd_range,
            "decision": decision,
            "score_breakdown": score_breakdown,
            "data_quality": data_quality_assessment,
        },
    )


