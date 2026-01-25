"""Tools for the Hello World example agent."""
from typing import Dict, Any

def echo_function(name: str = "World") -> Dict[str, Any]:
    """
    Generate a greeting message.
    
    Args:
        name: Name to greet (default: "World")
    
    Returns:
        Dictionary containing the greeting message
    """
    greeting = f"Hello, {name}! Welcome to Hive."
    
    return {
        "greeting": greeting,
        "success": True,
        "message": f"Greeting generated for '{name}'"
    }