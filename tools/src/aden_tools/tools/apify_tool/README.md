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

`apify_run_actor` starts a run and returns its `run_id`, `status` and `dataset_id`. Poll `apify_get_run` until the run finishes, then read the output with `apify_get_dataset_items`. The examples below share this helper:

```python
import time

def run_and_fetch(actor_id, input_data, limit=100):
    run = apify_run_actor(actor_id=actor_id, input_data=input_data)
    while run.get("status") in ("READY", "RUNNING"):
        time.sleep(5)
        run = apify_get_run(actor_id=actor_id, run_id=run["run_id"])
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"Actor run did not succeed: {run}")
    return apify_get_dataset_items(dataset_id=run["dataset_id"], limit=limit)["items"]
```

### Lead Generation

```python
# Find decision-makers on LinkedIn by job title and location
people = run_and_fetch(
    "johnvc/linkedin-people-search-api",
    {"jobTitle": "CEO", "location": "San Francisco", "maxResults": 25},
)
leads = [(p["fullName"], p["profileUrl"]) for p in people if p.get("profileUrl")]
```

### Market Research

```python
# Compare product prices across stores (Google Shopping)
items = run_and_fetch(
    "johnvc/google-shopping-api-google-shopping-products-prices-deals",
    {"q": "wireless headphones"},
)
offers = items[0]["shopping_results"]
prices = [o["extracted_price"] for o in offers if o.get("extracted_price")]
avg_price = sum(prices) / len(prices)
```

### Social Media Analytics

```python
# Get a YouTube video's transcript for sentiment analysis
items = run_and_fetch(
    "johnvc/YoutubeTranscripts",
    {"youtube_url": "https://youtube.com/watch?v=...", "output_formats": ["text"]},
)
transcript = items[0]["text"]
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
