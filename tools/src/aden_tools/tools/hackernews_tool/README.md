# HackerNews Tool

Fetch top Hacker News stories and story details including metadata and comments.
Provides highly structured, agent-friendly output without requiring authentication.

## Setup

No credentials required. Connects directly to the official [HackerNews Firebase API](https://github.com/HackerNews/API).

## Tools (2)

| Tool | Description |
|------|-------------|
| `get_top_hn_stories` | Fetch the top stories from Hacker News. |
| `get_hn_story_details` | Fetch specifics and top-level comments for a given story. |

## Limitations
- No authentication required.
- Implicit rate limits handled safely via sequential calls.
- Fetching comments is limited to top-level comments (max 20) to prevent excessively large context accumulation for agents.

## Example Usage

```python
# Get the top 5 stories
get_top_hn_stories(limit=5)

# Get details and comments for a specific story object
get_hn_story_details(story_id=40277319, include_comments=True, comment_limit=5)
```
