from fastmcp import FastMCP
from .schemas import PresentationSchema
from .powerpoint_core import generate_presentation


def register_tools(mcp: FastMCP, credentials=None) -> list[str]:
    @mcp.tool()
    def powerpoint_generate(input_data: dict) -> str:
        """
        Generate a PowerPoint presentation from structured slide schema.
        """
        try:

            schema = PresentationSchema(**input_data)
            return generate_presentation(schema)
        except Exception as e:
            raise RuntimeError(f"presentation generation failed: {str(e)}")

    return ["powerpoint_generate"]


