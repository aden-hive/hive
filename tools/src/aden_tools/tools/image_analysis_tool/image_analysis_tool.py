from typing import Optional
from fastmcp import FastMCP

def register_tools(mcp: FastMCP):
    """Register image analysis tools to the FastMCP server."""
    
    @mcp.tool()
    async def analyze_image(image_path: str, prompt: str = "Describe this image in detail") -> str:
        """
        Analyzes an image from a local path or URL and returns a description.
        Useful for understanding visual content or performing OCR.
        """
        # Şimdilik sistemin çalıştığını görmek için taslak cevap
        return f"Vision system placeholder: Analyzing '{image_path}' with prompt: '{prompt}'"

    return ["analyze_image"]