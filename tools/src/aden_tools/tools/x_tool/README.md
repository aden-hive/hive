# X (Twitter) Tool

Hive integration for the X (Twitter) API v2.

Enables agents to post tweets, reply to users, search recent tweets, and monitor mentions — allowing social automation workflows directly inside Hive.

## Features

- Post tweets
- Reply to tweets
- Delete tweets
- Search recent tweets
- Fetch user mentions

## Tools

| Tool | Description |
|--------|-------------|
| x_post_tweet | Post a new tweet |
| x_reply_tweet | Reply to an existing tweet |
| x_delete_tweet | Delete a tweet |
| x_search_tweets | Search recent tweets by query |
| x_get_mentions | Fetch mentions for a user |


## Authentication

This integration uses an **X API v2 Bearer Token**.

### Option 1 — Environment variable

export X_BEARER_TOKEN=your_token_here

### Option 2 — Hive credential store (recommended)

Configure credential id:

x

Hive will automatically inject credentials into all `x_*` tools.

## How to get a Bearer Token

1. Go to https://developer.x.com/
2. Create a Project & App
3. Enable API v2 access
4. Open **Keys & Tokens**
5. Copy the **Bearer Token**

## Example Usage

### Post a tweet

x_post_tweet("Hello from Hive 🚀")

### Reply to a tweet

x_reply_tweet(tweet_id="123456789", text="Thanks for the mention!")

### Search tweets

x_search_tweets(query="AI agents", max_results=5)

### Get mentions

x_get_mentions(user_id="2244994945")

## Notes

- Uses lightweight httpx client (no external SDK)
- Follows HubSpot tool architecture for consistency
- Compatible with Hive CredentialStoreAdapter
- Handles rate limits and common HTTP errors gracefully
- Max results capped at 100 per request (API limit)

## Development

Run tests:

pytest

Start MCP server:

python mcp_server.py
