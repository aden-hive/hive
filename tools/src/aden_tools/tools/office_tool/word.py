from fastmcp import FastMCP
from .word_core import generate_word
from .schemas import WordSchema


def register_tools(mcp: FastMCP, credentials=None) -> list[str]:
    @mcp.tool()
    def word_generate(input_data: dict) -> str:
        try:
            schema = WordSchema(**input_data)
            return generate_word(schema)
        except Exception as e:
            raise RuntimeError(f"word generation failed: {str(e)}")

    return ["word_generate"]



 