from fastmcp import FastMCP
from .excel_core import generate_excel
from .schemas import ExcelSchema


def register_tools(mcp: FastMCP, credentials=None) -> list[str]:

    @mcp.tool()
    def excel_generate(input_data: dict) -> str:
        try:
            schema = ExcelSchema(**input_data)
            return generate_excel(schema)
        except Exception as e:
            raise RuntimeError(f"Excel generation failed: {str(e)}")

    return ["excel_generate"]

