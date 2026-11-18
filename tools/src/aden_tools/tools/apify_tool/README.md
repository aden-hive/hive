# Apify Tool for Hive

Universal web scraping and automation through the Apify marketplace.

## Overview

Apify is a cloud platform providing a marketplace of thousands of ready-made web scrapers and automation tools ("Actors"). This integration allows Hive agents to extract structured data from almost any website without writing custom scraping code.

## Why Use This?

While agents can make raw HTTP requests, Apify interactions are complex:

1. **Async Polling**: Actor runs take time (seconds to minutes). `apify_run_actor` starts a run and returns its `run_id`, and `apify_get_run` reports the run's status, so an agent can check progress without building raw API requests.
2. **Dataset Abstraction**: Results live in the run's dataset. `apify_get_dataset_items` takes the `dataset_id` that the run returns and handles `limit`/`offset` paging.
3. **Security**: Keeps the `APIFY_API_TOKEN` in the credential store instead of exposing it to the agent context.

## Credential Setup

1. Sign up at [console.apify.com](https://console.apify.com)
2. Go to Settings → Integrations
3. Copy your Personal API token
4. Set as environment variable: `export APIFY_API_TOKEN=your_token_here`

## Tools

These are MCP tools that `register_tools` adds to the server, and agents call them through MCP. The Python snippets in this README show the same calls with the same arguments.

`actor_id` is an Actor ID or `owner~name` (for example `apify~web-scraper`). The tools put it straight into the API path, so use `~`, not `/`, between the owner and the name.

### `apify_run_actor`

Start an Actor run.

**Parameters:**

- `actor_id` (str): Actor ID or `owner~name`
- `input_data` (dict): JSON input for the Actor (optional)
- `memory_mbytes` (int): Memory in MB (optional, 0 = Actor default)
- `timeout_secs` (int): Run timeout in seconds (optional, 0 = Actor default)
- `build` (str): Build tag (optional)

**Example:**

```python
run = apify_run_actor(
    actor_id="apify~web-scraper",
    input_data={"startUrls": [{"url": "https://example.com"}]},
)
# Returns: {"run_id": "abc123", "status": "READY", "dataset_id": "xyz789", ...}
```

The call returns as soon as the run starts. Poll `apify_get_run` until `status` is `SUCCEEDED`, then read the results with `apify_get_dataset_items`.

### `apify_get_run`

Check the status of a run.

**Parameters:**

- `actor_id` (str): The same `actor_id` used to start the run
- `run_id` (str): Run ID returned by `apify_run_actor`

**Example:**

```python
status = apify_get_run(actor_id="apify~web-scraper", run_id="abc123")
# Returns: {"run_id": "abc123", "status": "SUCCEEDED", "dataset_id": "xyz789", "started_at": "...", "finished_at": "...", ...}
```

### `apify_get_dataset_items`

Read a run's results.

**Parameters:**

- `dataset_id` (str): Dataset ID from `apify_run_actor` or `apify_get_run`
- `limit` (int): Number of items (default 100)
- `offset` (int): Pagination offset (default 0)
- `format` (str): Output format (default `json`). The tool parses the response as JSON, so use `json`; other formats return an error.

**Example:**

```python
data = apify_get_dataset_items(dataset_id="xyz789", limit=50)
# Returns: {"items": [...], "count": 50}
```

### `apify_list_actors`

List the Actors in your Apify account.

**Parameters:**

- `limit` (int): Number of results (default 50)
- `offset` (int): Pagination offset (default 0)

### `apify_list_runs`

List recent runs, for one Actor or for all of them.

**Parameters:**

- `actor_id` (str): Actor to filter by (optional; empty lists all runs)
- `limit` (int): Number of results (default 50)
- `offset` (int): Pagination offset (default 0)

### `apify_get_kv_store_record`

Read one record from a key-value store, such as a run's `OUTPUT`.

**Parameters:**

- `store_id` (str): Key-value store ID (`kv_store_id` from `apify_get_run`)
- `key` (str): Record key

## Use Cases

The examples below share this helper, which starts a run, waits for it to finish and returns the first `limit` items (default 100). For larger runs, call `apify_get_dataset_items` again with an `offset`.

```python
import time

def run_and_fetch(actor_id, input_data, limit=100):
    actor_id = actor_id.replace("/", "~")  # the API path needs owner~name
    run = apify_run_actor(actor_id=actor_id, input_data=input_data)
    if "error" in run:
        raise RuntimeError(f"Could not start {actor_id}: {run['error']}")
    run_id, status, misses = run["run_id"], run["status"], 0
    while status in ("READY", "RUNNING"):
        time.sleep(5)
        check = apify_get_run(actor_id=actor_id, run_id=run_id)
        if "error" in check:  # a failed status check does not stop the run
            misses += 1
            if misses == 5:
                raise RuntimeError(f"Lost track of run {run_id} of {actor_id}: {check['error']}")
            continue
        status, run, misses = check["status"], check, 0
    if status != "SUCCEEDED":
        raise RuntimeError(f"Run {run_id} of {actor_id} ended with status {status}")
    data = apify_get_dataset_items(dataset_id=run["dataset_id"], limit=limit)
    if "error" in data:
        raise RuntimeError(f"Could not read results of run {run_id}: {data['error']}")
    return data["items"]
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
    {"youtube_url": "https://www.youtube.com/watch?v=1UL8iZJD38U", "output_formats": ["text"]},
)
row = items[0]
if "text" not in row:  # e.g. the video has no captions
    raise RuntimeError(row.get("error_message", "No transcript returned"))
transcript = row["text"]
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
