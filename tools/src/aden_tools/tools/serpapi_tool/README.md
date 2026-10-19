# SerpAPI Tool

Google Scholar & Google Patents search via SerpAPI.

## Description

Provides 5 tools for academic paper search, citation lookup, author profiles, and patent search. Google Scholar has no official API — SerpAPI is the only way to get structured paper metadata including citation counts and h-index data.

## Tools

### `scholar_search`

Search Google Scholar for academic papers.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | Search query (1-500 chars) |
| `num_results` | int | No | `10` | Results to return (1-20) |
| `start` | int | No | `0` | Pagination offset |
| `year_low` | int | No | - | Published after this year |
| `year_high` | int | No | - | Published before this year |
| `sort_by_date` | bool | No | `False` | Sort by date vs relevance |

### `scholar_get_citations`

Get citation formats (MLA, APA, Chicago, Harvard, Vancouver) for a paper.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `result_id` | str | Yes | The `result_id` from a `scholar_search` result |

### `scholar_get_author`

Get author profile with h-index, i10-index, total citations, and articles.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `author_id` | str | Yes | - | Google Scholar author ID |
| `num_articles` | int | No | `20` | Articles to return (1-100) |
| `start` | int | No | `0` | Pagination offset |
| `sort_by` | str | No | `citedby` | Sort: `citedby` or `pubdate` |

### `patents_search`

Search Google Patents.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `query` | str | Yes | - | Search query (1-500 chars) |
| `page` | int | No | `1` | Page number (1-indexed) |
| `country` | str | No | - | Country code (US, EP, WO, CN) |
| `status` | str | No | - | `GRANT` or `APPLICATION` |
| `before_date` | str | No | - | Filed before (YYYYMMDD) |
| `after_date` | str | No | - | Filed after (YYYYMMDD) |

### `patents_get_details`

Get full details for a specific patent.

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `patent_id` | str | Yes | Patent publication number (e.g. `US20210012345A1`) |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SERPAPI_API_KEY` | Yes | API key from [SerpAPI Dashboard](https://serpapi.com/manage-api-key) |

## Error Handling

Returns error dicts for common issues:
- `SerpAPI credentials not configured` - No API key set
- `Query must be 1-500 characters` - Invalid query length
- `Invalid SerpAPI API key` - Key rejected by API
- `SerpAPI rate limit exceeded` - Too many requests
- `Search request timed out` - Request exceeded 30s timeout
