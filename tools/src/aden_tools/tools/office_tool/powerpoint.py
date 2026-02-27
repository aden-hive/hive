from fastmcp import FastMCP
from .schemas import PresentationSchema
from .powerpoint_core import generate_presentation


def register_tools(mcp: FastMCP, credentials=None) -> list[str]:

    @mcp.tool()
    def powerpoint_generate(
        file_name: str,
        slides: list[dict],
        footer_text: str | None = None,
    ) -> str:
        """
        Generate a PowerPoint presentation from structured slide schema.
        """
        try:
            schema = PresentationSchema(
                file_name=file_name,
                slides=slides,
                footer_text=footer_text,
            )
            return generate_presentation(schema)
        except Exception as e:
            raise RuntimeError("PowerPoint generation failed.") from e

    return ["powerpoint_generate"]
