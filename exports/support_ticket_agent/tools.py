"""
Tools for support_ticket_agent.

This agent uses only llm_generate nodes, so no external tools are required.
This file demonstrates where tools would be defined if needed.

Example tool pattern:
    def my_tool(input_data: dict) -> dict:
        \"\"\"Tool description.\"\"\"
        # Implementation
        return {"result": "value"}
"""


def example_tool(input_data: dict) -> dict:
    """
    Example tool placeholder.
    
    This agent doesn't use tools, but this demonstrates the pattern
    for future extensions.
    
    Args:
        input_data: Input dictionary
        
    Returns:
        Result dictionary
    """
    return {"status": "not_used", "note": "This agent uses only LLM nodes"}
