# RSS-to-Twitter Thread Agent

Automated content repurposing from RSS feeds to Twitter/X threads. Fetches articles from configured RSS feeds, extracts key points, and generates engaging Twitter threads for user review.

## What It Does

1. **Fetches** articles from any RSS feed URL you provide
2. **Processes** the content and extracts key points
3. **Generates** a structured Twitter/X thread ready for posting or review

## Architecture

```
fetch → process → generate
```

| Node | Type | Description |
|------|------|-------------|
| `fetch` | event_loop | Fetches and parses RSS feed, extracts articles |
| `process` | event_loop | Extracts key points from articles |
| `generate` | event_loop (client-facing) | Generates Twitter thread, presents to user |

## Quick Start

### 1. Prerequisites

Make sure you have the Hive repo set up:
```bash
git clone https://github.com/adenhq/hive.git
cd hive
./quickstart.sh
```

### 2. Set your API key

This agent works with any LiteLLM-compatible provider. Choose one:

**Option A — Anthropic (Claude):**
```bash
export ANTHROPIC_API_KEY=your_key_here
```

**Option B — Groq (free tier available at console.groq.com):**
```bash
mkdir -p ~/.hive
echo '{"llm": {"provider": "groq", "model": "llama-3.3-70b-versatile"}}' > ~/.hive/configuration.json
export GROQ_API_KEY=your_key_here
```

**Option C — Any other provider:**
```bash
mkdir -p ~/.hive
echo '{"llm": {"provider": "your_provider", "model": "your_model"}}' > ~/.hive/configuration.json
export YOUR_PROVIDER_API_KEY=your_key_here
```

### 3. Run the agent

**Interactive TUI (recommended):**
```bash
PYTHONPATH=core uv run python -m examples.template.rss_twitter_agent tui
```

**Direct run:**
```bash
PYTHONPATH=core uv run python -m examples.template.rss_twitter_agent run --input '{"feed_url": "https://hnrss.org/frontpage"}'
```

**Validate agent structure:**
```bash
PYTHONPATH=core uv run python -m examples.template.rss_twitter_agent validate
```

**Show agent info:**
```bash
PYTHONPATH=core uv run python -m examples.template.rss_twitter_agent info
```

## Usage

Once the TUI is running, type your request in the chat panel. Examples:

```
Fetch posts from https://hnrss.org/frontpage and create a Twitter thread from the top story
```

```
Get the latest articles from https://feeds.feedburner.com/TechCrunch and generate a thread
```

```
Summarize https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml as a Twitter thread
```

## Configuration

The agent uses `config.py` for runtime settings. Key parameters:

| Setting | Default | Description |
|---------|---------|-------------|
| `model` | Auto-detected from `~/.hive/configuration.json` | LLM model to use |
| `temperature` | `0.7` | Response creativity |
| `max_tokens` | `8000` | Max output length |

To use a different model, create `~/.hive/configuration.json`:
```json
{
  "llm": {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile"
  }
}
```

## Twitter Posting Modes

The agent supports two modes for Twitter/X output:

| Mode | Description |
|------|-------------|
| **Draft (default)** | Generated threads are shown for review only. No posts are made to Twitter/X. |
| **Live** | Threads are actually posted to Twitter/X using your API credentials (OAuth 1.0a via tweepy). |

Set the mode with the `TWITTER_POST_MODE` environment variable:

```bash
export TWITTER_POST_MODE=draft   # default
export TWITTER_POST_MODE=live    # post to Twitter/X
```

### Optional: Twitter API credentials (for live mode)

To post in **live** mode, set these environment variables (get keys from the [Twitter / X Developer Portal](https://developer.twitter.com)):

| Variable | Description |
|----------|-------------|
| `TWITTER_POST_MODE` | `draft` or `live` (default: `draft`) |
| `TWITTER_BEARER_TOKEN` | Optional; OAuth 2.0 Bearer Token |
| `TWITTER_API_KEY` | OAuth 1.0a Consumer Key (API Key) |
| `TWITTER_API_SECRET` | OAuth 1.0a Consumer Secret |
| `TWITTER_ACCESS_TOKEN` | OAuth 1.0a Access Token |
| `TWITTER_ACCESS_SECRET` | OAuth 1.0a Access Token Secret |

Create an app at [developer.twitter.com](https://developer.twitter.com), enable **Read and Write** (or **Read and Write and Direct Messages**) for the app, then generate the Access Token and Secret. The agent uses OAuth 1.0a (API Key + Secret + Access Token + Access Secret) for posting.

**Fallback:** If `TWITTER_POST_MODE=live` but any required credential is missing, the agent falls back to draft behavior and notifies you (via the tool result) that credentials were not set. No post is made.

## Target Users

- Content marketers
- Social media managers
- Developer relations teams  
- Indie hackers / founders building in public

## Notes

- Any RSS feed URL works — blog posts, news sites, product updates
- The agent operates in **draft** mode by default (no auto-posting); set `TWITTER_POST_MODE=live` and API credentials to post. See [Twitter Posting Modes](#twitter-posting-modes) above.
- Requires Playwright for full web scraping: `pip install playwright && python -m playwright install chromium`
- Works with 100+ LLM providers via LiteLLM (Anthropic, Groq, OpenAI, Ollama, etc.)
