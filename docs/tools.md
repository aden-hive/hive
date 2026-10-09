# Tools

Hive agents work through **built-in tools** that run inside the Hive process, plus any **external MCP servers** you add. Agents never see the difference: every tool reaches the model as an ordinary function call.

## Built-in tools

The built-in tools are grouped by what they do. Each group runs in-process (no subprocess, no MCP session) and is defined in [`core/framework/tools/harness_tools.py`](../core/framework/tools/harness_tools.py).

| Group | Tools |
|---|---|
| `terminal-tools` | `terminal_exec`, background jobs (`terminal_job_*`), PTY sessions (`terminal_pty_*`, POSIX only), `terminal_rg`, `terminal_glob`, `terminal_output_get` |
| `files-tools` | `read_file`, `write_file`, `edit_file`, `search_files` |
| `chart-tools` | `chart_render` (ECharts and Mermaid to PNG) |
| `memory-tools` | `search_messages` (regex over past conversations); `search_timeline` (dated events, facts and plans the user mentioned) when the `memory_timeline` feature flag is on |
| `hive_tools` | `attach_file`, `pdf_read`, `web_scrape`, `get_current_time`, `get_account_info`, `image_generate`, the `csv_*` and `excel_*` tools; the email-senders suite when `HIVE_EMAIL_SENDERS` is on |

The browser is driven through the `hive-browser` CLI from `terminal_exec`; the in-process `browser_setup` tool makes it discoverable.

Group names work anywhere a server name does: allowlists, `@server:<name>` references in tool categories, and the Tool Library, which lists the groups as non-removable built-in rows.

## External MCP servers

Anything else comes from MCP servers you add:

```bash
hive mcp add          # register a local or running server
hive mcp install <n>  # install one from the registry
hive mcp list         # see what's installed
```

Servers you add are started for queens and workers automatically, and their tools join the same allowlists as the built-in ones. An agent package can also list servers in its own `mcp_servers.json`.

## The `aden_tools` integration catalog

`tools/src/aden_tools/tools/` still holds the full integration catalog (GitHub, Gmail, HubSpot, Notion, Slack, security scanners and more), but Hive no longer loads it: only the `hive_tools` subset above ships in-process. To use the full catalog, run it as an external server:

```bash
uv run python tools/mcp_server.py --stdio                                # verified integrations
INCLUDE_UNVERIFIED_TOOLS=true uv run python tools/mcp_server.py --stdio  # plus unverified ones
```

and register it with `hive mcp add`. Most integrations need credentials configured in Settings first.

## Adding a built-in tool

Write the tool as a function decorated with `@mcp.tool()` inside a `register_tools(mcp)` function, as the existing modules under `tools/src/` do, then call that function from the matching group builder in `harness_tools.py`. The harness builds the JSON schema from the type annotations and `Field` descriptions, validates arguments, and passes framework context (session working directory, agent identity) to parameters that declare it.

See the [developer guide](developer-guide.md) for the full contribution workflow.
