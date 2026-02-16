"""Liability analysis node - examines liability and indemnification clauses."""

from framework.graph.node import Node, NodeContext
from ..schemas import LiabilityFinding


async def liability_analysis_node(context: NodeContext) -> dict:
    """
    Analyze liability and indemnification provisions.
    
    Examines liability caps, indemnification type, and insurance requirements.
    
    Input:
        - full_text: Contract text
        
    Output:
        - liability: LiabilityFinding object
    """
    input_data = context.input_data
    text = input_data.get("full_text", "")
    
    prompt = f"""Analyze the liability and indemnification provisions in this contract:

Contract text:
{text[:5000]}

Provide detailed analysis in JSON format:
{{
    "cap_present": true/false,
    "cap_amount": "dollar amount as string or null",
    "unlimited_liability": true/false,
    "indemnification_type": "mutual" | "one-sided" | "none",
    "insurance_required": true/false,
    "risk_level": "low" | "medium" | "high",
    "concerns": ["list of specific liability concerns"]
}}

Focus on:
1. Is there a cap on liability? What is the amount?
2. Does any party have unlimited liability?
3. Is indemnification mutual or one-sided?
4. Is insurance required?
5. Are there any unusual or risky liability provisions?
"""
    
    try:
        response = await context.llm.ainvoke(
            prompt=prompt,
            temperature=0.2,
            response_format="json"
        )
        
        import json
        analysis = json.loads(response)
        
        finding = LiabilityFinding(**analysis)
        
        return {
            "success": True,
            "liability": finding.model_dump(),
        }
        
    except Exception as e:
        return {
            "success": False,
            "liability": LiabilityFinding(
                cap_present=False,
                cap_amount=None,
                unlimited_liability=True,
                indemnification_type="unclear",
                insurance_required=False,
                risk_level="high",
                concerns=[f"Analysis failed: {str(e)}"]
            ).model_dump(),
            "error": str(e)
        }


# Create the node instance
liability_node = Node(
    id="liability_analysis",
    fn=liability_analysis_node,
    name="Liability Analysis",
    description="Analyzes liability caps and indemnification provisions",
)
