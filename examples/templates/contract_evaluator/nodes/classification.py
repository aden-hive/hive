"""Classification node - identifies contract type and jurisdiction."""

from framework.graph.node import Node, NodeContext
from ..schemas import ContractMetadata, ContractType, Jurisdiction


async def classification_node(context: NodeContext) -> dict:
    """
    Classify the contract and extract basic metadata.
    
    Uses LLM to determine contract type, jurisdiction, and parties.
    
    Input:
        - full_text: Contract text
        - contract_id: Unique identifier
        
    Output:
        - metadata: ContractMetadata object
        - is_nda: Boolean indicating if this is an NDA
        - classification_confidence: Confidence score
    """
    input_data = context.input_data
    text = input_data.get("full_text", "")
    contract_id = input_data.get("contract_id", "unknown")
    
    if not text:
        return {
            "success": False,
            "error": "No text provided for classification"
        }
    
    # Use LLM to classify the contract
    prompt = f"""Analyze this contract and extract the following information:

1. Contract Type: Is this an NDA, Mutual NDA, One-Sided NDA, or something else?
2. Jurisdiction: Which legal jurisdiction governs this contract?
3. Parties: Who are the two main parties?
4. Effective Date: When does the contract start?
5. Expiration Date: When does it end (if specified)?

Contract text (first 3000 characters):
{text[:3000]}

Provide your analysis in JSON format with these exact fields:
- contract_type: one of ["NDA", "Mutual NDA", "One-Sided NDA", "Unknown"]
- jurisdiction: specific state/country or "Unknown"
- party_a: first party name or null
- party_b: second party name or null
- effective_date: date in YYYY-MM-DD format or null
- expiration_date: date in YYYY-MM-DD format or null
- confidence: float between 0 and 1
"""
    
    try:
        # Call LLM with structured output
        response = await context.llm.ainvoke(
            prompt=prompt,
            temperature=0.1,  # Low temperature for consistency
            response_format="json"
        )
        
        # Parse LLM response
        import json
        analysis = json.loads(response)
        
        # Map to enum types
        contract_type_str = analysis.get("contract_type", "Unknown")
        if "Mutual" in contract_type_str:
            contract_type = ContractType.MUTUAL_NDA
        elif "One-Sided" in contract_type_str or "One Sided" in contract_type_str:
            contract_type = ContractType.ONE_SIDED_NDA
        elif "NDA" in contract_type_str:
            contract_type = ContractType.NDA
        else:
            contract_type = ContractType.UNKNOWN
        
        # Map jurisdiction
        jurisdiction_str = analysis.get("jurisdiction", "Unknown")
        jurisdiction = Jurisdiction.UNKNOWN
        for j in Jurisdiction:
            if j.value.lower() in jurisdiction_str.lower():
                jurisdiction = j
                break
        
        # Create metadata object
        metadata = ContractMetadata(
            contract_id=contract_id,
            contract_type=contract_type,
            jurisdiction=jurisdiction,
            confidence=analysis.get("confidence", 0.5),
            party_a=analysis.get("party_a"),
            party_b=analysis.get("party_b"),
            effective_date=analysis.get("effective_date"),
            expiration_date=analysis.get("expiration_date"),
            page_count=input_data.get("page_count"),
            word_count=input_data.get("word_count"),
        )
        
        is_nda = contract_type in [
            ContractType.NDA,
            ContractType.MUTUAL_NDA,
            ContractType.ONE_SIDED_NDA
        ]
        
        return {
            "success": True,
            "metadata": metadata.model_dump(),
            "is_nda": is_nda,
            "classification_confidence": metadata.confidence,
        }
        
    except Exception as e:
        # Fallback classification
        return {
            "success": True,
            "metadata": ContractMetadata(
                contract_id=contract_id,
                contract_type=ContractType.UNKNOWN,
                jurisdiction=Jurisdiction.UNKNOWN,
                confidence=0.3,
                page_count=input_data.get("page_count"),
                word_count=input_data.get("word_count"),
            ).model_dump(),
            "is_nda": False,
            "classification_confidence": 0.3,
            "error": f"Classification failed: {str(e)}. Using fallback."
        }


# Create the node instance
classify_node = Node(
    id="classification",
    fn=classification_node,
    name="Contract Classification",
    description="Identifies contract type, jurisdiction, and basic metadata",
)
