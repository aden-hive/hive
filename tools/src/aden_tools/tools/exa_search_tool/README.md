# Exa Search Tool

AI-powered web search and content extraction using the Exa (formerly Metaphor) API.

## Description

Exa is a neural search engine that understands semantic meaning rather than just keywords. Use this tool for high-quality research, finding similar pages, extracting clean page content, and getting citation-backed answers.

## Tools

### exa_search
Search the web using Exa's AI-powered neural or keyword search.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | The search query (1-500 chars) |
| `num_results` | int | No | `10` | Number of results (1-20) |
| `search_type` | str | No | `"auto"` | Mode: "auto", "neural" (semantic), or "keyword" |
| `include_domains` | list | No | `None` | Only include results from these domains |
| `exclude_domains` | list | No | `None` | Exclude results from these domains |
| `start_published_date`| str | No | `None` | Filter by publish date start (ISO 8601, e.g. "2024-01-01") |
| `end_published_date` | str | No | `None` | Filter results published before this date (ISO 8601) |
| `include_text` | bool | No | `True` | Include full page text in results |
| `include_highlights` | bool | No | `False` | Include relevant text highlights |
| `category` | str | No | `None` | Category filter (e.g. "research paper", "news", "company") |

### exa_find_similar
Find web pages semantically similar to a given URL.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `url` | str | Yes | - | The source URL to find similar pages for |
| `num_results` | int | No | `10` | Number of similar results (1-20) |
| `include_domains` | list | No | `None` | Only include results from these domains |
| `exclude_domains` | list | No | `None` | Exclude results from these domains |
| `include_text` | bool | No | `True` | Include full page text in results |

### exa_get_contents
Extract clean content (text and highlights) from one or more URLs.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `urls` | list | Yes | - | List of URLs to extract content from (1-10 URLs) |
| `include_text` | bool | No | `True` | Include full page text |
| `include_highlights` | bool | No | `False` | Include relevant text highlights |

### exa_answer
Get a direct answer to a question with citations from web sources.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | The question to answer (1-500 chars) |
| `include_citations` | bool | No | `True` | Include source citations in the response |

### Specialized Search Wrappers

The toolkit also includes convenience wrappers for specific content types:
- **exa_search_news**: Pre-configured for recent news with `days_back` filter.
- **exa_search_papers**: Pre-configured for research papers with `year_start` filter.
- **exa_search_companies**: Pre-configured for company and startup discovery.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `EXA_API_KEY` | Yes | API key from [Exa Dashboard](https://dashboard.exa.ai/) |

## Example Usage

```python
# Semantic search for specific topics
result = exa_search(query="latest breakthroughs in battery technology", category="research paper")

# Find similar content
result = exa_find_similar(url="https://example.com/blog-post")

# Get an answer with citations
result = exa_answer(query="What are the current top 3 AI companies in Japan?")

# Search recent news
result = exa_search_news(query="Nvidia stock", days_back=2)
```

## Error Handling

Returns error dicts for common issues:
- `Exa credentials not configured` - Missing `EXA_API_KEY`
- `Invalid Exa API key` - API key rejected (401)
- `Exa rate limit exceeded` - Too many requests (429)
- `Query must be 1-500 characters` - Invalid query length
- `Maximum 10 URLs per request` - URL list too long for `exa_get_contents`
- `Exa search request timed out` - Request timed out (30s)
