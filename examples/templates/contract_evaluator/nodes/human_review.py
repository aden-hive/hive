"""Human review node - escalates to human when needed."""

from framework.graph.node import Node, NodeContext


async def human_review_node(context: NodeContext) -> dict:
    """
    Human-in-the-loop review for high-risk contracts.
    
    This node only executes if human review is required based on risk assessment.
    Presents findings to a human reviewer and waits for their feedback.
    
    Input:
        - risk_assessment: RiskAssessment object
        - metadata: Contract metadata
        
    Output:
        - review_approved: Boolean
        - reviewer_notes: String
        - reviewer_feedback: Dict
    """
    input_data = context.input_data
    
    risk_assessment = input_data.get("risk_assessment", {})
    metadata = input_data.get("metadata", {})
    
    # Prepare review summary for human
    review_data = {
        "contract_id": metadata.get("contract_id"),
        "contract_type": metadata.get("contract_type"),
        "overall_risk_score": risk_assessment.get("overall_risk_score"),
        "critical_issues": risk_assessment.get("critical_issues", []),
        "moderate_issues": risk_assessment.get("moderate_issues", []),
        "recommendations": risk_assessment.get("recommendations", []),
        "reason_for_review": risk_assessment.get("human_review_reason"),
    }
    
    # Request human input
    # Note: In Hive, this would pause execution and present data to user via TUI
    human_response = await context.request_human_input(
        message=f"High-risk contract detected: {metadata.get('contract_id')}. Please review the findings.",
        data=review_data,
        timeout_seconds=3600,  # 1 hour timeout
    )
    
    # Process human feedback
    approved = human_response.get("approve", False)
    notes = human_response.get("notes", "")
    
    return {
        "success": True,
        "review_approved": approved,
        "reviewer_notes": notes,
        "reviewer_feedback": human_response,
        "review_timestamp": context.execution_id,  # Use execution ID as timestamp
    }


# Create the node instance
human_review_node_instance = Node(
    id="human_review",
    fn=human_review_node,
    name="Human Review",
    description="Escalates high-risk contracts to human legal reviewer",
)
