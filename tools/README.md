# Aden Tools

Tool library for the Aden agent framework. Provides a collection of tools that AI agents can use to interact with external systems, process data, and perform actions via the Model Context Protocol (MCP).

## Installation

```bash
uv pip install -e tools
```

For development:

```bash
uv pip install -e "tools[dev]"
```

## Environment Setup

Some tools require API keys to function. Credentials are managed through the encrypted credential store at `~/.hive/credentials`, which is configured automatically during initial setup:

```bash
./quickstart.sh
```

| Variable               | Required For                  | Get Key                                                 |
| ---------------------- | ----------------------------- | ------------------------------------------------------- |
| `ANTHROPIC_API_KEY`    | MCP server startup, LLM nodes | [console.anthropic.com](https://console.anthropic.com/) |
| `BRAVE_SEARCH_API_KEY` | `web_search` tool (Brave)     | [brave.com/search/api](https://brave.com/search/api/)   |
| `GOOGLE_API_KEY`       | `web_search` tool (Google)    | [console.cloud.google.com](https://console.cloud.google.com/) |
| `GOOGLE_CSE_ID`        | `web_search` tool (Google)    | [programmablesearchengine.google.com](https://programmablesearchengine.google.com/) |

> **Note:** `web_search` supports multiple providers. Set either Brave OR Google credentials. Brave is preferred for backward compatibility.

Alternatively, export credentials as environment variables:

```bash
export ANTHROPIC_API_KEY=your-key-here
export BRAVE_SEARCH_API_KEY=your-key-here
```

See the [credentials module](src/aden_tools/credentials/) for details on how credentials are resolved.

## Quick Start

### As an MCP Server

```python
from fastmcp import FastMCP
from aden_tools.tools import register_all_tools

mcp = FastMCP("tools")
register_all_tools(mcp)
mcp.run()
```

Or run directly:

```bash
python mcp_server.py
```

## Available Tools

### File System

| Tool | Description |
| ---- | ----------- |
| `view_file` | Read contents of local files |
| `write_to_file` | Write content to local files |
| `list_dir` | List directory contents |
| `replace_file_content` | Replace content in files |
| `apply_diff` | Apply diff patches to files |
| `apply_patch` | Apply unified patches to files |
| `grep_search` | Search file contents with regex |
| `execute_command_tool` | Execute shell commands |
| `save_data` / `load_data` | Persist and retrieve structured data across steps |
| `serve_file_to_user` | Serve a file for the user to download |
| `list_data_files` | List persisted data files in the session |
| `append_data` / `edit_data` | Append or edit persisted data files |

### Data Files

| Tool | Description |
| ---- | ----------- |
| `csv_read` | Read rows from a CSV file |
| `csv_write` | Write a new CSV file |
| `csv_append` | Append rows to a CSV file |
| `csv_info` | Get CSV file metadata |
| `csv_sql` | Query a CSV file with SQL (DuckDB) |
| `excel_read` | Read rows from an Excel sheet |
| `excel_write` | Write a new Excel file |
| `excel_append` | Append rows to an Excel file |
| `excel_info` | Get Excel file metadata |
| `excel_sheet_list` | List sheets in an Excel workbook |
| `excel_sql` | Query Excel sheets with SQL (DuckDB) |
| `excel_search` | Search for values across Excel sheets |
| `pdf_read` | Read and extract text from PDF files |

### Web & Search

| Tool | Description |
| ---- | ----------- |
| `web_search` | Search the web (Google or Brave, auto-detected) |
| `web_scrape` | Scrape and extract content from webpages |
| `search_wikipedia` | Search Wikipedia for pages and summaries |
| `scholar_search`, `scholar_get_citations`, `scholar_get_author` | Search academic papers, get citations and author profiles via SerpAPI |
| `patents_search`, `patents_get_details` | Search patents and retrieve patent details via SerpAPI |
| `exa_search`, `exa_answer`, `exa_find_similar`, `exa_get_contents` | Semantic search and content retrieval via Exa AI |
| `news_search`, `news_headlines`, `news_by_company`, `news_sentiment` | Search news articles and analyse sentiment |
| `search_papers`, `download_paper` | Search arXiv for scientific papers and download PDFs |

### Communication

| Tool | Description |
| ---- | ----------- |
| `gmail_*` | Read, reply, draft, and manage Gmail messages |
| `send_email` | Send email via SMTP |
| `slack_*` | Send messages, manage channels, users, and files in Slack |
| `discord_send_message`, `discord_get_messages`, `discord_list_channels`, `discord_list_guilds` | Send and read Discord messages |
| `telegram_send_message`, `telegram_send_document` | Send messages and documents via Telegram Bot API |

### Productivity & CRM

| Tool | Description |
| ---- | ----------- |
| `calendar_list_calendars` | List all accessible calendars |
| `calendar_list_events` | List events from a calendar |
| `calendar_get_event` | Get details of a specific event |
| `calendar_create_event` | Create a new calendar event |
| `calendar_update_event` | Update an existing calendar event |
| `calendar_delete_event` | Delete a calendar event |
| `calendar_get_calendar` | Get calendar metadata |
| `calendar_check_availability` | Check free/busy status for attendees |
| `hubspot_*` | HubSpot CRM: contacts, companies, deals, notes |
| `apollo_*` | Apollo.io: prospect search and enrichment |
| `calcom_*` | Cal.com: scheduling and bookings |

### Cloud & APIs

| Tool | Description |
| ---- | ----------- |
| `vision_*` | Analyze images with Google Cloud Vision (labels, OCR, faces, objects, etc.) |
| `google_docs_*` | Read and write Google Docs |
| `maps_*` | Places search, geocoding, directions (Google Maps) |
| `run_bigquery_query`, `describe_dataset` | Run queries against Google BigQuery |
| `razorpay_*` | Razorpay payments and orders |
| `github_*` | GitHub repos, issues, and pull requests |

### Security

| Tool | Description |
| ---- | ----------- |
| `port_scan` | TCP port scan with service banner grabbing |
| `dns_security_scan` | Check SPF, DMARC, DKIM, DNSSEC, zone transfer |
| `ssl_tls_scan` | Analyze SSL/TLS configuration and certificate |
| `http_headers_scan` | Check security-related HTTP response headers |
| `subdomain_enumerate` | Enumerate subdomains via DNS |
| `tech_stack_detect` | Detect technologies used by a website |
| `risk_score` | Compute an overall security risk grade |

### Utilities

| Tool | Description |
| ---- | ----------- |
| `get_current_time` | Get current date/time with timezone support |
| `query_runtime_logs`, `query_runtime_log_details`, `query_runtime_log_raw` | Access agent runtime logs for the current session |

## Project Structure

```
tools/
├── src/aden_tools/
│   ├── __init__.py          # Main exports
│   ├── credentials/         # Credential management
│   └── tools/               # Tool implementations
│       ├── example_tool/
│       ├── file_system_toolkits/  # File operation tools
│       │   ├── view_file.py
│       │   ├── write_to_file.py
│       │   ├── list_dir.py
│       │   ├── replace_file_content.py
│       │   ├── apply_diff.py
│       │   ├── apply_patch.py
│       │   ├── grep_search.py
│       │   └── execute_command_tool.py
│       ├── web_search_tool/
│       ├── web_scrape_tool/
│       ├── pdf_read_tool/
│       ├── wikipedia_tool/
│       ├── time_tool/
│       └── calendar_tool/
├── tests/                   # Test suite
├── mcp_server.py            # MCP server entry point
├── README.md
├── BUILDING_TOOLS.md        # Tool development guide
└── pyproject.toml
```

## Creating Custom Tools

Tools use FastMCP's native decorator pattern:

```python
from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def my_tool(query: str, limit: int = 10) -> dict:
        """
        Search for items matching the query.

        Args:
            query: The search query
            limit: Max results to return

        Returns:
            Dict with results or error
        """
        try:
            results = do_search(query, limit)
            return {"results": results, "total": len(results)}
        except Exception as e:
            return {"error": str(e)}
```

See [BUILDING_TOOLS.md](BUILDING_TOOLS.md) for the full guide.

## Documentation

- [Building Tools Guide](BUILDING_TOOLS.md) - How to create new tools
- Individual tool READMEs in `src/aden_tools/tools/*/README.md`

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](../LICENSE) file for details.
