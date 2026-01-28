from typing import Dict, Any

def greet(name: str) -> Dict[str, str]:
    """
    Generate a simple greeting.
    
    Args:
        name: The name to greet
        
    Returns:
        Dictionary containing the greeting
    """
    return {"greeting": f"Hello, {name}!"}
