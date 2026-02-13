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

Full catalog: `docs/tools-catalog.md`.

### Core

`example_tool`

### Web

`web_search`, `web_scrape`

### Documents

`pdf_read`

### File system

`view_file`, `write_to_file`, `list_dir`, `replace_file_content`, `apply_diff`, `apply_patch`, `grep_search`, `execute_command_tool`

### Data files

`load_data`, `save_data`, `list_data_files`, `serve_file_to_user`

### CSV

`csv_read`, `csv_write`, `csv_append`, `csv_info`, `csv_sql`

### Apollo

`apollo_enrich_person`, `apollo_enrich_company`, `apollo_search_people`, `apollo_search_companies`

### GitHub

`github_list_repos`, `github_get_repo`, `github_search_repos`, `github_list_issues`, `github_get_issue`, `github_create_issue`, `github_update_issue`, `github_list_pull_requests`, `github_get_pull_request`, `github_create_pull_request`, `github_search_code`, `github_list_branches`, `github_get_branch`, `github_list_stargazers`, `github_get_user_profile`, `github_get_user_emails`

### Email

`send_email`, `send_budget_alert_email`

### HubSpot

`hubspot_search_contacts`, `hubspot_get_contact`, `hubspot_create_contact`, `hubspot_update_contact`, `hubspot_search_companies`, `hubspot_get_company`, `hubspot_create_company`, `hubspot_update_company`, `hubspot_search_deals`, `hubspot_get_deal`, `hubspot_create_deal`, `hubspot_update_deal`

### Runtime logs

`query_runtime_logs`, `query_runtime_log_details`, `query_runtime_log_raw`

### Slack

`slack_send_message`, `slack_list_channels`, `slack_get_channel_history`, `slack_add_reaction`, `slack_get_user_info`, `slack_update_message`, `slack_delete_message`, `slack_schedule_message`, `slack_create_channel`, `slack_archive_channel`, `slack_invite_to_channel`, `slack_set_channel_topic`, `slack_remove_reaction`, `slack_list_users`, `slack_upload_file`, `slack_search_messages`, `slack_get_thread_replies`, `slack_pin_message`, `slack_unpin_message`, `slack_list_pins`, `slack_add_bookmark`, `slack_list_scheduled_messages`, `slack_delete_scheduled_message`, `slack_send_dm`, `slack_get_permalink`, `slack_send_ephemeral`, `slack_post_blocks`, `slack_open_modal`, `slack_update_home_tab`, `slack_set_status`, `slack_set_presence`, `slack_get_presence`, `slack_create_reminder`, `slack_list_reminders`, `slack_delete_reminder`, `slack_create_usergroup`, `slack_update_usergroup_members`, `slack_list_usergroups`, `slack_list_emoji`, `slack_create_canvas`, `slack_edit_canvas`, `slack_get_messages_for_analysis`, `slack_trigger_workflow`, `slack_get_conversation_context`, `slack_find_user_by_email`, `slack_kick_user_from_channel`, `slack_delete_file`, `slack_get_team_stats`

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
│       └── pdf_read_tool/
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
