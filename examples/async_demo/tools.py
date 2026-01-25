import asyncio
import random
from framework.runner.tool_registry import tool

@tool(description="Perform heavy research asynchronously")
async def simulate_research(topic: str, duration_ms: int = 1000) -> str:
    """
    Simulates a heavy research task with async I/O delay.
    
    Args:
        topic: The topic to research
        duration_ms: How long to 'research' in milliseconds
        
    Returns:
        Mock research data
    """
    print(f"  [AsyncTool] Starting research on '{topic}' ({duration_ms}ms)...")
    await asyncio.sleep(duration_ms / 1000)
    print(f"  [AsyncTool] Finished research on '{topic}'")
    return f"Detailed analysis of {topic} completed in {duration_ms}ms. Key findings: {random.randint(1, 100)} data points."
