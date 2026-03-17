# Apify Tool for Hive

Universal web scraping and automation through the Apify marketplace.

## Overview

Apify is a cloud platform providing a marketplace of thousands of ready-made web scrapers and automation tools ("Actors"). This integration allows Hive agents to extract structured data from almost any website without writing custom scraping code.

## Why Use This?

While agents can make raw HTTP requests, Apify interactions are complex:

1. **Async Polling**: Actor runs take time (seconds to minutes). A raw request just returns a `runId`, requiring the agent to loop, sleep, and poll status—which LLMs struggle with.
2. **Dataset Abstraction**: Fetching results requires knowing specific dataset IDs and pagination logic. This tool abstracts that into a simple `wait=True` parameter.
3. **Security**: Keeps the `APIFY_API_TOKEN` in the credential store instead of exposing it to the agent context.

## Credential Setup

1. Sign up at [console.apify.com](https://console.apify.com)
2. Go to Settings → Integrations
3. Copy your Personal API token
4. Set as environment variable: `export APIFY_API_TOKEN=your_token_here`

## Tools

### `apify_run_actor`

Run an Apify Actor to scrape or automate websites.

**Parameters:**

- `actor_id` (str): Actor identifier (e.g., `"apify/instagram-scraper"`)
- `input` (dict): JSON input specific to the actor (default: `{}`)
- `wait` (bool): If `True`, waits for completion and returns results immediately. If `False`, returns `runId` for async status checks (default: `True`)

**Example:**

```python
# Synchronous execution (recommended)
result = apify_run_actor(
    actor_id="apify/instagram-profile-scraper",
    input={"usernames": ["instagram", "google"]},
    wait=True
)
# Returns: {"items": [...], "run_id": "...", "status": "SUCCEEDED"}

# Asynchronous execution
result = apify_run_actor(
    actor_id="apify/web-scraper",
    input={"startUrls": [{"url": "https://example.com"}]},
    wait=False
)
# Returns: {"run_id": "abc123", "status": "RUNNING"}
```

### `apify_get_dataset`

Retrieve results from a completed actor run.

**Parameters:**

- `dataset_id` (str): Dataset identifier from a completed run

**Example:**

```python
data = apify_get_dataset(dataset_id="xyz789")
# Returns: {"items": [...], "count": 42}
```

### `apify_get_run`

Check the status of an actor run.

**Parameters:**

- `run_id` (str): Run identifier returned from `apify_run_actor` with `wait=False`

**Example:**

```python
status = apify_get_run(run_id="abc123")
# Returns: {"status": "SUCCEEDED", "default_dataset_id": "xyz789", ...}
```

### `apify_search_actors`

Search the Apify marketplace for actors (optional).

**Parameters:**

- `query` (str): Search keywords
- `limit` (int): Maximum results to return (default: 10)

**Example:**

```python
actors = apify_search_actors(query="instagram", limit=5)
# Returns: {"items": [...], "total": 24}
```

## Use Cases

### Lead Generation

```python
# Find email addresses of decision-makers on LinkedIn
result = apify_run_actor(
    actor_id="apify/linkedin-profile-scraper",
    input={"search": "CEO at tech company in SF"},
    wait=True
)
emails = [p["email"] for p in result["items"] if p.get("email")]
```

### Market Research

```python
# Monitor product prices across multiple platforms
result = apify_run_actor(
    actor_id="apify/amazon-scraper",
    input={"search": "wireless headphones", "maxItems": 50},
    wait=True
)
prices = [item["price"] for item in result["items"]]
avg_price = sum(prices) / len(prices)
```

### Social Media Analytics

```python
# Analyze YouTube video comments for sentiment
result = apify_run_actor(
    actor_id="apify/youtube-scraper",
    input={"videoUrls": ["https://youtube.com/watch?v=..."]},
    wait=True
)
comments = result["items"][0]["comments"]
```

## Error Handling

All tools return `{"error": "message", "help": "..."}` on failure:

- Missing credentials
- Invalid actor ID
- Actor not found (404)
- Rate limit exceeded (429)
- Network timeouts
- Invalid API token (401)

## API Documentation

- [Apify API v2](https://docs.apify.com/api/v2)
- [Actor Marketplace](https://apify.com/store)
