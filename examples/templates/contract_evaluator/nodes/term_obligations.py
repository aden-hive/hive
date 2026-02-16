"""Term and obligations node - extracts term length and key obligations."""

from framework.graph.node import Node, NodeContext
from ..schemas import TermObligation


async def term_obligations_node(context: NodeContext) -> dict:
    """
    Extract contract term, renewal conditions, and key obligations.
    
    Input:
        - full_text: Contract text
        
    Output:
        - terms: TermObligation object
    """
    input_data = context.input_data
    text = input_data.get("full_text", "")
    
    prompt = f"""Analyze the term and obligations in this contract:

Contract text:
{text[:5000]}

Provide detailed analysis in JSON format:
{{
    "duration_months": number or null,
    "auto_renewal": true/false,
    "notice_period_days": number or null,
    "termination_for_convenience": true/false,
    "key_obligations": ["list of main obligations"],
    "deliverables": ["list of deliverables if any"],
    "risk_level": "low" | "medium" | "high",
    "concerns": ["list of concerns about terms"]
}}

Focus on:
1. What is the contract duration?
2. Does it auto-renew? What's the notice period?
3. Can either party terminate for convenience?
4. What are the key obligations of each party?
5. Are there concerning term provisions?
"""
    
    try:
        response = await context.llm.ainvoke(
            prompt=prompt,
            temperature=0.2,
            response_format="json"
        )
        
        import json
        analysis = json.loads(response)
        
        finding = TermObligation(**analysis)
        
        return {
            "success": True,
            "terms": finding.model_dump(),
        }
        
    except Exception as e:
        return {
            "success": False,
            "terms": TermObligation(
                duration_months=None,
                auto_renewal=False,
                notice_period_days=None,
                termination_for_convenience=False,
                key_obligations=[],
                deliverables=[],
                risk_level="medium",
                concerns=[f"Analysis failed: {str(e)}"]
            ).model_dump(),
            "error": str(e)
        }


# Create the node instance
terms_node = Node(
    id="term_obligations",
    fn=term_obligations_node,
    name="Term & Obligations Analysis",
    description="Extracts contract duration, renewal terms, and obligations",
)
