"""Synthesis node - aggregates findings and calculates risk score."""

from framework.graph.node import Node, NodeContext
from ..schemas import RiskAssessment, ClauseFindings


async def synthesis_node(context: NodeContext) -> dict:
    """
    Aggregate all analysis findings and calculate overall risk assessment.
    
    Input:
        - confidentiality: ConfidentialityFinding
        - liability: LiabilityFinding
        - terms: TermObligation
        - metadata: Contract metadata
        
    Output:
        - risk_assessment: RiskAssessment object
        - clause_findings: ClauseFindings object
    """
    input_data = context.input_data
    
    # Get all findings
    confidentiality = input_data.get("confidentiality", {})
    liability = input_data.get("liability", {})
    terms = input_data.get("terms", {})
    
    # Calculate risk scores from risk levels
    risk_map = {"low": 3, "medium": 6, "high": 9}
    
    conf_risk = risk_map.get(confidentiality.get("risk_level", "medium"), 6)
    liab_risk = risk_map.get(liability.get("risk_level", "medium"), 6)
    term_risk = risk_map.get(terms.get("risk_level", "medium"), 6)
    
    # Weighted average (liability is most important)
    overall_risk = (conf_risk * 0.3 + liab_risk * 0.5 + term_risk * 0.2)
    
    # Collect all concerns
    critical_issues = []
    moderate_issues = []
    
    # Check for critical issues
    if liability.get("unlimited_liability"):
        critical_issues.append("Unlimited liability exposure detected")
    
    if confidentiality.get("type") == "one-sided" and conf_risk >= 6:
        critical_issues.append("One-sided confidentiality obligations")
    
    if liability.get("indemnification_type") == "one-sided":
        critical_issues.append("One-sided indemnification clause")
    
    # Collect moderate issues from concerns
    all_concerns = (
        confidentiality.get("concerns", []) +
        liability.get("concerns", []) +
        terms.get("concerns", [])
    )
    
    # Separate critical from moderate
    for concern in all_concerns:
        if any(word in concern.lower() for word in ["unlimited", "no cap", "indefinite"]):
            if concern not in critical_issues:
                critical_issues.append(concern)
        else:
            moderate_issues.append(concern)
    
    # Generate recommendations
    recommendations = []
    
    if not liability.get("cap_present"):
        recommendations.append("Add limitation of liability clause with reasonable cap")
    
    if confidentiality.get("type") == "one-sided":
        recommendations.append("Negotiate for mutual confidentiality obligations")
    
    if liability.get("indemnification_type") == "one-sided":
        recommendations.append("Request bilateral indemnification")
    
    if terms.get("auto_renewal") and not terms.get("notice_period_days"):
        recommendations.append("Clarify notice period for non-renewal")
    
    # Determine if human review is needed
    risk_threshold = float(input_data.get("risk_threshold", 7.0))
    needs_review = overall_risk >= risk_threshold or len(critical_issues) > 0
    
    review_reason = None
    if needs_review:
        if overall_risk >= risk_threshold:
            review_reason = f"High risk score ({overall_risk:.1f}/10) exceeds threshold ({risk_threshold})"
        elif critical_issues:
            review_reason = f"Critical issues detected: {len(critical_issues)} items"
    
    # Create risk assessment
    risk_assessment = RiskAssessment(
        overall_risk_score=overall_risk,
        confidentiality_risk=float(conf_risk),
        liability_risk=float(liab_risk),
        terms_risk=float(term_risk),
        critical_issues=critical_issues,
        moderate_issues=moderate_issues[:10],  # Limit to top 10
        recommendations=recommendations,
        human_review_required=needs_review,
        human_review_reason=review_reason,
        compliance_flags=[],  # Could add GDPR/CCPA checks here
    )
    
    return {
        "success": True,
        "risk_assessment": risk_assessment.model_dump(),
        "overall_risk_score": overall_risk,
        "needs_human_review": needs_review,
    }


# Create the node instance
synthesis_node_instance = Node(
    id="synthesis",
    fn=synthesis_node,
    name="Synthesis & Risk Assessment",
    description="Aggregates findings and calculates overall risk score",
)
