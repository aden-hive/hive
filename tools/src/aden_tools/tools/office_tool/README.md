# Office Tools

Schema-driven Office document generation tools for the Aden agent framework.

This module provides structured generation of:

- Excel files (`.xlsx`)
- Word documents (`.docx`)
- PowerPoint presentations (`.pptx`)

All tools follow a schema-first architecture using Pydantic models and integrate with FastMCP.

---

## Installation

Office tools use optional dependencies.

Install with:

```bash
pip install tools[office]


 Or install manually:
'''bash 
pip install openpyxl python-docx python-pptx

Available TOOLS

| Tool                  | Description                                                |
| --------------------- | ---------------------------------------------------------- |
| `excel_generate`      | Generate Excel files with formulas, formatting, and charts |
| `word_generate`       | Generate Word documents with headings, tables, and images  |
| `powerpoint_generate` | Generate PowerPoint slides with charts and tables          |


## Excel Features

- Multiple sheets support
- Formula columns (must start with `=`)
- Column formatting (width, number format, alignment)
- Conditional formatting (greater_than / less_than)
- Auto filter support
- Chart generation (Line, Bar)
- Header freeze (`A2`)
- Automatic column width adjustment
- Row and sheet limit validation
- Deterministic export path handling

## Word Features

- Headings (levels 0–9)
- Bullet and numbered lists
- Styled paragraphs
- Bold / italic text support
- Paragraph alignment (left, center, right)
- Tables with styled headers
- Image embedding with optional width
- Page breaks
- Header and footer support
- Structured schema-driven document generation

## PowerPoint Features

- Multiple slide layouts (title, content, blank)
- Title support
- Bullet lists with indentation levels
- Table generation
- Chart generation (Line, Bar)
- Slide notes support
- Background image support
- Embedded images with positioning
- Footer text support
- Structured slide schema validation

