# Maintainer Service - MCP Refactored

Intelligent GitHub issue & PR management service using Hive Framework MCP Tools.

## Architecture

This service uses **Model Context Protocol (MCP)** tools from `aden_tools` instead of custom client implementations:

- **GitHub API**: Uses `github_tool` via MCP instead of direct `httpx` calls
- **Email**: Uses `email_tool` via MCP instead of `smt plib`
- **Vector DB**: Uses `vector_db_tool` via MCP instead of direct ChromaDB

### Benefits
✅ Reusable tools across multiple agents  
✅ Centralized credential management  
✅ Consistent error handling  
✅ Easier testing and mocking  

## Key Files

### `app/mcp_client.py` *(NEW)*
Central MCP client that registers all `aden_tools` and provides a simple API for other modules.

### `app/github_client.py` *(REFACTORED)*
Thin wrapper around `github_tool` MCP. Maintains same interface as before but delegates to MCP.

### `app/memory.py` *(REFACTORED)*
Uses `vector_db_tool` MCP for ChromaDB operations instead of direct `chromadb` library calls.

### `app/notifier.py` *(REFACTORED)*
Uses `email_tool` MCP for sending digest emails instead of `smtplib`.

### `app/triage.py`, `app/llm.py`, etc.
No changes required - these use the refactored dependencies.

## Setup

### 1. Install Dependencies

```bash
cd /path/to/hive
pip install -e tools/  # Install aden_tools
pip install -e maintainer_service/
```

### 2. Configure Environment

Create `maintainer_service/.env`:

```bash
# GitHub
GITHUB_TOKEN=ghp_...
GITHUB_REPO_OWNER=adenhq
GITHUB_REPO_NAME=hive

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=bot@example.com
SMTP_PASSWORD=app_password
NOTIFICATION_EMAIL=maintainers@example.com

# Vector DB
CHROMA_PERSIST_DIRECTORY=./data/chroma

# LLM
OPENAI_API_KEY=sk-...

# Service Config
ANALYSIS_INTERVAL_MINUTES=60
```

### 3. Run Service

```bash
cd maintainer_service
python -m app.main
```

## How MCP Integration Works

```python
# Before (Custom Implementation)
import httpx
response = httpx.get(f"https://api.github.com/repos/{repo}/issues")
issues = response.json()

# After (MCP Tool)
from app.mcp_client import mcp_client
issues = mcp_client.get_issues(state="open")
```

The `mcp_client` module:
1. Initializes `FastMCP` server
2. Registers `aden_tools` (github, email, vector_db)
3. Provides clean wrapper methods
4. Handles credential injection from env vars

## Testing

```bash
# Test MCP client
python -c "from app.mcp_client import mcp_client; print(mcp_client.get_issues(per_page=1))"

# Run full service
python -m app.main
```

## Migration Notes

- **Removed**: `httpx`, `smtplib`, direct `chromadb` imports
- **Added**: `mcp_client.py`, updated imports in existing files
- **No breaking changes**: Public APIs remain the same
