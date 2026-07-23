# HackerNews Tool Integration

Provides real-time access to HackerNews using the official Firebase API.

## Tools

- `get_top_stories(limit: int = 10)`: Retrieves the current top stories on HackerNews.
- `get_item(item_id: int)`: Retrieves details for a specific HackerNews item (story, comment, poll, etc.).

## Usage

This tool is integrated directly into the Hive `aden_tools` framework and doesn't require any API keys or credentials, as it uses the public Firebase API.

## Example

An agent can use this tool to fetch the latest tech news:

```json
{
  "name": "get_top_stories",
  "arguments": {
    "limit": 5
  }
}
```
