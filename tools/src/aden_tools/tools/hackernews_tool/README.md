# HackerNews Tool

This tool integrates with [HackerNews](https://news.ycombinator.com/) to provide news retrieval and search capabilities for AI agents. It uses the public Firebase API for fetching stories and the Algolia API for search, requiring **no API keys**.

## Why this matters for agents

HackerNews is a rich source of technical discourse and emerging trends. With this tool, agents can perform:
- **Trend Discovery:** Monitor top stories to detect emerging frameworks, models, or topics.
- **Technical Signal Detection:** Analyze high-quality discussions for sentiment on technical choices.
- **Startup Intelligence:** Track competitor news, product launches (Show HN), or funding events.
- **Dev Ecosystem Monitoring:** Keep developers informed about critical ecosystem updates or security vulnerabilities.

## Features

- **Top Stories**: Fetch the current top stories on HN, with built-in async concurrency and a TTL cache for fast performance.
- **Search**: Search for specific keywords or topics using Algolia's HackerNews Search API.
- **Item Lookup**: Fetch specific items (stories, comments) by their ID.
- **Filtering**: Apply filters like `min_score` to reduce noise.
- **Stable Schema**: Returns normalized story metadata (`id`, `title`, `url`, `score`, `by`, `time`, `descendants`, `type`) using Pydantic validation.

## Tools

### `hn_get_top_stories`
Retrieves the top stories currently on Hacker News.
- `limit` (int, default 10): Maximum number of stories to return (1-50).
- `min_score` (int, default 0): Filter out stories with fewer points than this to reduce noise.

### `hn_search_stories`
Search Hacker News for stories matching a keyword using the Algolia Search API.
- `query` (str): The search keyword or phrase (e.g., "LLM", "OpenAI").
- `limit` (int, default 10): Maximum number of results to return (1-50).

### `hn_get_item`
Fetch details of a specific item from Hacker News by its ID.
- `item_id` (int): The ID of the Hacker News item.

## Environment Variables

None. This tool does not require any credentials.

## Error Handling

The tool correctly identifies and handles dead or deleted items. It returns an error dict if network requests fail or invalid arguments are provided:
```json
{
  "error": "Failed to fetch top stories: [Error details]"
}
```
