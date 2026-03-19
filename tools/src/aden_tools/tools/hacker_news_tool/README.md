# Hacker News Tool

Search Hacker News and fetch the front page. Uses the Algolia HN Search API (no key required).

## Use Cases

- **News agents**: Find trending tech news and product launches
- **Research agents**: Gather community discussions on a topic
- **Content agents**: Discover popular stories for curation

## Tools

| Tool | Description |
|------|-------------|
| `hacker_news_search` | Search stories by query (relevance or date) |
| `hacker_news_front_page` | Get current front page stories |

## Usage

```python
# Search for AI-related stories
hacker_news_search(query="AI agents", max_results=5)

# Get front page
hacker_news_front_page(max_results=10)
```

## Arguments

### hacker_news_search

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| query | str | required | Search term |
| max_results | int | 10 | Results to return (1-20) |
| sort_by | str | "relevance" | relevance or date |
| tags | str | "" | Filter: story, ask_hn, show_hn, front_page |

### hacker_news_front_page

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| max_results | int | 10 | Stories to return (1-20) |

## Error Handling

Returns `{"error": "message"}` on failure.
