# PDF Reader Tool

Read and extract text from PDF files using the MCP Server.

## Files

```
pdf-reader/
├── README.md              # This documentation
├── read_pdf_example.py    # Example script (3 methods)
└── sample_document.pdf    # Test PDF file (2 pages)
```

---

## Quick Usage

```python
import sys
sys.path.insert(0, 'tools/src')
from fastmcp import FastMCP
from aden_tools.tools.pdf_read_tool import register_tools

mcp = FastMCP('test')
register_tools(mcp)
pdf_read = mcp._tool_manager._tools['pdf_read'].fn

# Read PDF
result = pdf_read(file_path='docs/test-scripts/pdf-reader/sample_document.pdf', pages='all')
print(result['content'])
```

---

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to PDF file |
| `pages` | string | `"all"` | `'all'`, `'1'`, `'1-5'`, `'1,3,5'` |
| `max_pages` | int | `100` | Safety limit (max 1000) |
| `include_metadata` | bool | `True` | Include PDF metadata |

---

## Run Example

```bash
cd d:\projects\interview\hive\hive
python docs/test-scripts/pdf-reader/read_pdf_example.py
```
