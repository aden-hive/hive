"""An AI agent that analyzes SME companies and evaluates their credit risk, including probability of default, financial strength, and lending recommendation."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    financial_analysis_node,
    risk_assessment_node,
    credit_decision_node,
)

# Goal definition
goal = Goal(
    id="sme-credit-risk-assessment",
    name="SME Credit Risk Assessment",
    description=(
        "Evaluate SME credit applications by analyzing financial data, cash flows, "
        "risk factors, and mitigants in order to estimate probability of default "
	"and issue a lending recommendation."
    ),
    success_criteria=[
        SuccessCriterion(
            id="risk-identification",
            description="All material credit risk factors are identified and explained",
            metric="risk_coverage",
            target="high",
            weight=0.3,
        ),
        SuccessCriterion(
            id="repayment-capacity",
            description="Cash flow and repayment capacity are correctly assessed and supports debt repayment",
            metric="dscr_accuracy",
            target=">=1.1",
            weight=0.3,
        ),
        SuccessCriterion(
            id="decision-quality",
            description="Credit decision is justified and consistent with risk profile",
            metric="decision_consistency",
            target="high",
            weight=0.4,
        ),
    )

# Node list
nodes = [
    intake_node,
    financial_analysis_node,
    risk_assessment_node,
    credit_decision_node,
]

# Edge definitions
edges = [
    # intake -> financial_analysis
    EdgeSpec(
        id="intake-to-financial",
        source="intake",
        target="financial_analysis",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # financial_analysis -> risk_assessment
    EdgeSpec(
        id="financial-to-risk",
        source="financial_analysis",
        target="risk_assessment",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # risk_assessment -> credit_decision
    EdgeSpec(
        id="risk-to-decision",
        source="risk_assessment",
        target="credit_decision",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
terminal_nodes = ["credit_decision"]
pause_nodes = []


class CreditRiskAgent:
    """
    Credit Risk Agent — 4-node pipeline with user checkpoints.

    Flow: intake -> financial_analysis -> risk_assessment -> credit_decision

    """

    pass
