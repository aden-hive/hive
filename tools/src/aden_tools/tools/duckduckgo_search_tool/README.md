# DuckDuckGo Search Tool

Perform free web searches using DuckDuckGo without requiring any external API keys or authentication.

## Supported Actions

- **duckduckgo_search** – Search the web for a given query and return a list of results containing titles, links, and snippets.

## Limits & Validation

- **Max results**: Configurable via the `max_results` parameter (defaults to 5 to avoid overwhelming the context window).
- **Rate limits**: Relies on DuckDuckGo's public endpoints. Aggressive or rapid-fire querying might result in temporary IP bans from DuckDuckGo.
- **Empty queries**: Validates against empty strings before sending the request to the search engine.

## Setup

1. Unlike other search tools (like Exa or Apollo), this tool **does not require an API key**.
2. It runs entirely on the open-source `duckduckgo-search` Python package.

Ensure the dependency is installed in your environment:

```bash
uv add duckduckgo-searchS
```
## Use Case

Example: "Can you search the web for the best settings to optimize a 180Hz monitor for competitive gaming and give me a quick list?"