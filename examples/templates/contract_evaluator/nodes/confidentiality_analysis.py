"""Confidentiality analysis node - analyzes confidentiality clauses."""

from framework.graph.node import Node, NodeContext
from ..schemas import ConfidentialityFinding


async def confidentiality_analysis_node(context: NodeContext) -> dict:
    """
    Analyze confidentiality clauses in the contract.
    
    Examines mutual vs one-sided obligations, scope, exceptions, and duration.
    
    Input:
        - full_text: Contract text
        
    Output:
        - confidentiality: ConfidentialityFinding object
    """
    input_data = context.input_data
    text = input_data.get("full_text", "")
    
    prompt = f"""Analyze the confidentiality provisions in this NDA:

Contract text:
{text[:5000]}

Provide detailed analysis in JSON format:
{{
    "type": "mutual" | "one-sided" | "unclear",
    "scope": "brief description of what information is covered",
    "exceptions": ["list of exceptions like publicly available, independently developed"],
    "duration_months": number or null,
    "return_materials_required": true/false,
    "risk_level": "low" | "medium" | "high",
    "concerns": ["list of specific concerns if any"]
}}

Focus on:
1. Is confidentiality mutual or does it favor one party?
2. What types of information are covered?
3. What are the standard exceptions?
4. How long does the confidentiality obligation last?
5. Any unusual or concerning provisions?
"""
    
    try:
        response = await context.llm.ainvoke(
            prompt=prompt,
            temperature=0.2,
            response_format="json"
        )
        
        import json
        analysis = json.loads(response)
        
        finding = ConfidentialityFinding(**analysis)
        
        return {
            "success": True,
            "confidentiality": finding.model_dump(),
        }
        
    except Exception as e:
        # Fallback analysis
        return {
            "success": False,
            "confidentiality": ConfidentialityFinding(
                type="unclear",
                scope="Analysis failed",
                exceptions=[],
                duration_months=None,
                return_materials_required=False,
                risk_level="high",
                concerns=[f"Automated analysis failed: {str(e)}"]
            ).model_dump(),
            "error": str(e)
        }


# Create the node instance
confidentiality_node = Node(
    id="confidentiality_analysis",
    fn=confidentiality_analysis_node,
    name="Confidentiality Analysis",
    description="Analyzes confidentiality obligations and scope",
)
