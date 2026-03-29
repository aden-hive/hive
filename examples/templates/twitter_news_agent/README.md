# Twitter News Digest

Monitors tech Twitter profiles, extracts the latest tweets, and compiles a daily tech news digest with user review.

## Nodes

| Node | Type | Description |
|------|------|-------------|
| `fetch-tweets` | `gcu` (browser) | Navigates to Twitter profiles and extracts latest tweets |
| `process-news` | `event_loop` | Analyzes and summarizes tweets into a tech digest |
| `review-digest` | `event_loop` (client-facing) | Presents digest for user review and feedback |

## Flow

```
process-news → review-digest → (loop back to process-news)
      ↓                ↑
 fetch-tweets      feedback loop (if revisions needed)
 (sub-agent)
```

## Tools used

- **save_data / load_data** — persist daily reports
- **Browser (GCU)** — automated Twitter browsing and tweet extraction

## Running

```bash
uv run python -m examples.templates.twitter_news_agent run
uv run python -m examples.templates.twitter_news_agent run --handles "@TechCrunch,@verge,@WIRED"
```
