from typing import Any
import math
from core.framework.llm.provider import Tool, ToolResult, ToolUse

# 1. Define the Schema (What the LLM sees)
CALCULATOR_TOOL = Tool(
    name="calculator",
    description="Perform mathematical calculations. Use this for ANY math usage (addition, subtraction, multiplication, division, roots, trig). Input must be a valid python expression string.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate (e.g., '2 + 2 * 5', 'math.sqrt(16)')"
            }
        },
        "required": ["expression"]
    }
)

# 2. Define the Logic (What runs on the CPU)
def execute_calculator(tool_use: ToolUse) -> ToolResult:
    """Safely evaluate a math expression using Python's math library."""
    expression = tool_use.input.get("expression", "")
    
    # Security: Only allow specific math functions, no system access
    allowed_names = {
        k: v for k, v in math.__dict__.items() 
        if not k.startswith("__")
    }
    allowed_names.update({
        "abs": abs, 
        "round": round, 
        "min": min, 
        "max": max,
        "pow": pow
    })
    
    try:
        # Eval is risky, so we restrict globals to empty and locals to math functions only
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        
        return ToolResult(
            tool_use_id=tool_use.id,
            content=str(result),
            is_error=False
        )
    except Exception as e:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=f"Calculation Error: {str(e)}",
            is_error=True
        )
