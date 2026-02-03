# MCP Server Test Scripts

Test scripts for the Hive MCP Tools Server.

## Prerequisites

```bash
cd d:\projects\interview\hive\hive
$env:PYTHONPATH="tools/src;core"; python tools/mcp_server.py --port 4001
```

---

## Folder Structure

```
test-scripts/
├── README.md           # This file
├── test_mcp_tools.py   # General MCP tools test
└── pdf-reader/         # PDF Reader Tool
    ├── README.md       # PDF tool documentation
    └── read_pdf_example.py  # PDF reading examples
```

---

## Scripts

### `test_mcp_tools.py`
Basic test suite for MCP server.

```bash
python docs/test-scripts/test_mcp_tools.py
```

---

### `pdf-reader/`
Separate folder for PDF reading tools. See [pdf-reader/README.md](pdf-reader/README.md)

```bash
python docs/test-scripts/pdf-reader/read_pdf_example.py
```

---

## Related Docs

- [MCP Server Usage](../MCP_SERVER_USAGE.md)
- [MCP Server Guide](../../core/MCP_SERVER_GUIDE.md)
