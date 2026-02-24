# Wikipedia Search Tool

This tool allows agents to search Wikipedia and retrieve article summaries without needing an external API key.

## Features

- **Search**: Find relevant Wikipedia articles by query.
- **Summaries**: Get concise descriptions and excerpts for search results.
- **Multilingual**: Supports searching in different languages (default: English).
- **No API Key**: Uses the public Wikipedia REST API.

## Usage

### As an MCP Tool

```python
result = await call_tool(
    "search_wikipedia",
    arguments={
        "query": "Artificial Intelligence",
        "num_results": 3,
        "lang": "en"
    }
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | Required | The search term to look for. |
| `num_results` | `int` | `3` | Number of results to return (max 10). |
| `lang` | `str` | `"en"` | Wikipedia language code (e.g., "en", "es", "fr"). |

## Response Format

The tool returns a dictionary with the following structure:

```json
{
  "query": "Artificial Intelligence",
  "lang": "en",
  "count": 3,
  "results": [
    {
      "title": "Artificial intelligence",
      "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
      "description": "Intelligence of machines",
      "snippet": "Artificial intelligence (AI), in its broadest sense, is intelligence exhibited by machines, particularly the computer systems..."
    },
    ...
  ]
}
```
