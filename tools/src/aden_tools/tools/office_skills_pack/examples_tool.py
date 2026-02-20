from __future__ import annotations

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_skills_schema_examples() -> dict:
        return {
            "chart": {
                "title": "Example",
                "x_label": "x",
                "y_label": "y",
                "series": [{"name": "s1", "x": [1, 2, 3], "y": [1, 4, 9]}],
            },
            "excel": {
                "sheets": [{"name": "Sheet1", "columns": ["A", "B"], "rows": [[1, 2], [3, 4]]}],
            },
            "powerpoint": {
                "title": "Deck",
                "slides": [{"title": "Slide", "bullets": ["One"], "image_paths": [], "charts": []}],
            },
            "word": {
                "title": "Doc",
                "sections": [{"heading": "Intro", "paragraphs": ["Hello"], "bullets": []}],
            },
            "pack": {
                "strict": True,
                "charts": [],
                "xlsx_path": "out/report.xlsx",
                "pptx_path": "out/report.pptx",
                "docx_path": "out/report.docx",
                "workbook": {"sheets": [{"name": "Sheet1", "columns": ["A"], "rows": [[1]]}]},
                "deck": {
                    "title": "Deck",
                    "slides": [{"title": "S1", "bullets": [], "image_paths": [], "charts": []}],
                },
                "doc": {"title": "Doc", "sections": [{"heading": "H", "paragraphs": ["P"], "bullets": []}]},
            },
        }
