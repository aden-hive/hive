# Hive MCP Tools Server Documentation

## Quick Start

```bash
# Start the server
cd d:\projects\interview\hive\hive
$env:PYTHONPATH="tools/src;core"; python tools/mcp_server.py --port 4001
```

**Server URL**: `http://localhost:4001`

---

## HTTP Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Welcome page |
| `/health` | GET | Health check (returns "OK") |
| `/mcp/v1` | POST | MCP JSON-RPC endpoint |

### Test Health Check
```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:4001/health').read().decode())"
# Output: OK
```

---

## Available Tools

### Document Processing
| Tool | Description |
|------|-------------|
| `pdf_read` | Extract text from PDF files |
| `csv_read` | Read CSV files |
| `csv_write` | Write CSV files |
| `csv_append` | Append to CSV files |
| `csv_info` | Get CSV metadata |
| `csv_sql` | Query CSV with SQL |

### File System
| Tool | Description |
|------|-------------|
| `view_file` | View file contents |
| `write_to_file` | Write to files |
| `list_dir` | List directory contents |
| `grep_search` | Search files |
| `replace_file_content` | Replace file content |
| `apply_diff` | Apply diff patches |
| `apply_patch` | Apply patches |
| `execute_command_tool` | Run shell commands |

### Web Tools
| Tool | Description |
|------|-------------|
| `web_search` | Search the web (Google/Brave) |
| `web_scrape` | Scrape web pages |

### Integration Tools
| Tool | Description |
|------|-------------|
| `send_email` | Send emails via Resend |
| `hubspot_*` | HubSpot CRM operations |

---

## Usage Examples

### 1. Read PDF (Python Direct)

```python
import sys
sys.path.insert(0, 'tools/src')
from fastmcp import FastMCP
from aden_tools.tools.pdf_read_tool import register_tools

mcp = FastMCP('test')
register_tools(mcp)
pdf_read = mcp._tool_manager._tools['pdf_read'].fn

result = pdf_read(
    file_path='document.pdf',
    pages='all',          # 'all', '1', '1-5', '1,3,5'
    max_pages=100,
    include_metadata=True
)

print(result['content'])
```

### 2. JSON-RPC Request (HTTP)

```python
import urllib.request
import json

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "pdf_read",
        "arguments": {
            "file_path": "C:/path/to/file.pdf",
            "pages": "all"
        }
    }
}

req = urllib.request.Request(
    'http://localhost:4001/mcp/v1',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)
response = urllib.request.urlopen(req)
result = json.loads(response.read())
```

### 3. Test Script

```bash
python test_mcp_tools.py
```

---

## Tool Parameters

### pdf_read
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to PDF file |
| `pages` | string | "all" | 'all', '1', '1-5', '1,3,5' |
| `max_pages` | int | 100 | Safety limit (max 1000) |
| `include_metadata` | bool | true | Include PDF metadata |

### web_scrape
| Parameter | Type | Description |
|-----------|------|-------------|
| `url` | string | URL to scrape |

### web_search
| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query |

---

## Environment Variables

```env
# LLM Provider (choose one)
GEMINI_API_KEY="your-gemini-key"
ANTHROPIC_API_KEY="sk-ant-..."
OPENAI_API_KEY="sk-..."

# Tool Credentials
BRAVE_SEARCH_API_KEY="your-brave-key"
RESEND_API_KEY="your-resend-key"
HUBSPOT_ACCESS_TOKEN="your-hubspot-token"
```

---

## Server Modes

| Mode | Command | Use Case |
|------|---------|----------|
| HTTP | `--port 4001` | Testing, Docker, cloud |
| STDIO | `--stdio` | Claude Desktop, Cursor IDE |

---

## Troubleshooting

### Server won't start
```bash
pip install -r tools/requirements.txt
pip install resend hubspot-api-client
```

### Module not found
```bash
$env:PYTHONPATH="tools/src;core"
```

### Verify installation
```bash
python core/verify_mcp.py
```
