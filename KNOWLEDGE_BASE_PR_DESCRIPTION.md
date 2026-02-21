# [Feature]: Agent-accessible external knowledge bases

Resolves #2974

## Problem Statement

Agents currently lack the ability to access and leverage external knowledge bases, documentation, and APIs during business process execution. This limits their reasoning, context-awareness, and decision quality.

## Solution

This PR introduces a **Knowledge Base Tool** that provides connectors for agents to access popular knowledge sources in real-time:

### Supported Sources

| Source | Type | Description |
|--------|------|-------------|
| **Confluence** | Company Wiki | Search and retrieve content from Atlassian Confluence |
| **Notion** | Workspace | Search and retrieve content from Notion workspaces |
| **Documentation Portals** | Web Docs | Crawl and search generic documentation websites |

### Tools Provided

| Tool | Description |
|------|-------------|
| `confluence_search` | Search Confluence wiki using CQL with space and content type filters |
| `confluence_get_page` | Retrieve specific pages with full content and attachments |
| `notion_search` | Search Notion workspace for pages and databases |
| `notion_get_page` | Retrieve specific pages with content and optional blocks |
| `docs_search` | Crawl and search documentation portals by URL |
| `docs_get_page` | Retrieve content from documentation pages with code extraction |
| `knowledge_base_list_sources` | List available sources and their configuration status |

## Usage Examples

### Search Confluence
```json
{
  "query": "vacation policy",
  "space_key": "HR",
  "limit": 10
}
```

### Search Notion
```json
{
  "query": "project roadmap",
  "filter_type": "page"
}
```

### Search Documentation Portal
```json
{
  "base_url": "https://docs.python.org/3/",
  "query": "async await",
  "search_paths": ["/reference/", "/tutorial/"]
}
```

## Configuration

### Confluence
```bash
export CONFLUENCE_API_TOKEN="your-api-token"
export CONFLUENCE_URL="https://your-company.atlassian.net/wiki"
```
Get token: https://id.atlassian.com/manage-profile/security/api-tokens

### Notion
```bash
export NOTION_API_KEY="your-integration-token"
```
Create integration: https://www.notion.so/my-integrations

## Files Changed

### New Files
- `tools/src/aden_tools/tools/knowledge_base_tool/knowledge_base_tool.py` - Main implementation
- `tools/src/aden_tools/tools/knowledge_base_tool/__init__.py` - Module exports
- `tools/src/aden_tools/tools/knowledge_base_tool/README.md` - Documentation
- `tools/src/aden_tools/credentials/knowledge_base.py` - Credential specs
- `tools/tests/tools/test_knowledge_base_tool.py` - Test suite

### Modified Files
- `tools/src/aden_tools/credentials/__init__.py` - Register knowledge base credentials
- `tools/src/aden_tools/tools/__init__.py` - Register knowledge base tools

## Testing

- Unit tests for all tool functions
- Input validation tests
- Credential handling tests
- Tool registration tests

## Checklist

- [x] Implementation follows Hive tool patterns
- [x] Credential specs properly defined
- [x] Tests written for all tools
- [x] README documentation provided
- [x] Error handling with helpful messages
- [x] No hardcoded credentials
