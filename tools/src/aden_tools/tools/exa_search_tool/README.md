# Exa Search Tool

AI-powered web search, content extraction, and research using the Exa API.

## Description

Provides four tools for interacting with web content:

- **`exa_search`** — Neural/keyword web search with domain and date filters
- **`exa_find_similar`** — Find pages similar to a given URL
- **`exa_get_contents`** — Extract full text from URLs
- **`exa_answer`** — Get citation-backed answers to questions

## Arguments

### `exa_search`

| Argument               | Type      | Required | Default | Description                                     |
| ---------------------- | --------- | -------- | ------- | ----------------------------------------------- |
| `query`                | str       | Yes      | -       | The search query (1-500 chars)                  |
| `num_results`          | int       | No       | `10`    | Number of results (1-20)                        |
| `search_type`          | str       | No       | `auto`  | Search mode: "auto", "neural", or "keyword"     |
| `include_domains`      | list[str] | No       | `None`  | Only include results from these domains         |
| `exclude_domains`      | list[str] | No       | `None`  | Exclude results from these domains              |
| `start_published_date` | str       | No       | `None`  | Filter by publish date (ISO 8601)               |
| `end_published_date`   | str       | No       | `None`  | Filter by publish date (ISO 8601)               |
| `include_text`         | bool      | No       | `True`  | Include full page text                          |
| `include_highlights`   | bool      | No       | `False` | Include relevant text highlights                |
| `category`             | str       | No       | `None`  | Category filter (e.g. "research paper", "news") |

### `exa_find_similar`

| Argument          | Type      | Required | Default | Description                             |
| ----------------- | --------- | -------- | ------- | --------------------------------------- |
| `url`             | str       | Yes      | -       | Source URL to find similar pages for    |
| `num_results`     | int       | No       | `10`    | Number of results (1-20)                |
| `include_domains` | list[str] | No       | `None`  | Only include results from these domains |
| `exclude_domains` | list[str] | No       | `None`  | Exclude results from these domains      |
| `include_text`    | bool      | No       | `True`  | Include full page text                  |

### `exa_get_contents`

| Argument             | Type      | Required | Default | Description                         |
| -------------------- | --------- | -------- | ------- | ----------------------------------- |
| `urls`               | list[str] | Yes      | -       | URLs to extract content from (1-10) |
| `include_text`       | bool      | No       | `True`  | Include full page text              |
| `include_highlights` | bool      | No       | `False` | Include relevant highlights         |

### `exa_answer`

| Argument            | Type | Required | Default | Description                          |
| ------------------- | ---- | -------- | ------- | ------------------------------------ |
| `query`             | str  | Yes      | -       | The question to answer (1-500 chars) |
| `include_citations` | bool | No       | `True`  | Include source citations             |

## Environment Variables

| Variable      | Required | Description                                                     |
| ------------- | -------- | --------------------------------------------------------------- |
| `EXA_API_KEY` | Yes      | API key from [Exa Dashboard](https://dashboard.exa.ai/api-keys) |

## Example Usage

```python
# Neural web search
result = exa_search(query="latest advances in quantum computing")

# Search with filters
result = exa_search(
    query="AI safety research",
    search_type="neural",
    include_domains=["arxiv.org", "openai.com"],
    start_published_date="2024-01-01",
    num_results=5,
)

# Find pages similar to a URL
result = exa_find_similar(url="https://example.com/article")

# Extract content from URLs
result = exa_get_contents(urls=["https://example.com/page1", "https://example.com/page2"])

# Get a citation-backed answer
result = exa_answer(query="What are the main causes of climate change?")
```

## Error Handling

Returns error dicts for common issues:

- `Exa credentials not configured` - EXA_API_KEY not set
- `Query must be 1-500 characters` - Empty or too long query
- `URL is required` - Missing URL for find_similar
- `At least one URL is required` - Empty URL list for get_contents
- `Maximum 10 URLs per request` - Too many URLs for get_contents
- `Invalid Exa API key` - API key rejected (401)
- `Exa rate limit exceeded` - Too many requests (429)
- `Exa search request timed out` - Request exceeded 30s timeout
