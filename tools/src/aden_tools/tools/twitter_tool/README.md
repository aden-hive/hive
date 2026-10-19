# Twitter Tool

Tweet search, user lookup, and timeline access via the X (Twitter) API v2.

## Tools

| Tool | Description |
|------|-------------|
| `twitter_search_tweets` | Search recent tweets from the last 7 days |
| `twitter_get_user` | Get a user profile by username |
| `twitter_get_user_tweets` | Get recent tweets from a user's timeline |
| `twitter_get_tweet` | Get details of a specific tweet by ID |
| `twitter_get_user_followers` | Get followers of a user |
| `twitter_get_tweet_replies` | Get replies to a specific tweet |
| `twitter_get_list_tweets` | Get recent tweets from a Twitter/X list |

## Setup

Requires an X (Twitter) Bearer Token for read-only API v2 access:

1. Go to [developer.x.com](https://developer.x.com) → **Projects & Apps → Your App → Keys and Tokens**
2. Copy the **Bearer Token** under **Authentication Tokens**

```bash
X_BEARER_TOKEN=your-bearer-token
```

> The Bearer Token provides read-only access. Write operations (post, like, retweet) are not supported by this tool.

## Usage Examples

### Search recent tweets

```python
twitter_search_tweets(
    query="python machine learning -is:retweet lang:en",
    max_results=25,
    sort_order="recency",
)
```

### Search tweets from a specific user

```python
twitter_search_tweets(query="from:openai has:media", max_results=10)
```

### Get a user profile

```python
twitter_get_user(username="elonmusk")
```

### Get a user's recent tweets

```python
twitter_get_user_tweets(
    user_id="44196397",
    max_results=20,
    exclude_replies=True,
    exclude_retweets=True,
)
```

### Get a specific tweet

```python
twitter_get_tweet(tweet_id="1234567890123456789")
```

### Get followers of a user

```python
twitter_get_user_followers(user_id="44196397", max_results=50)
```

### Get replies to a tweet

```python
twitter_get_tweet_replies(tweet_id="1234567890123456789", max_results=20)
```

### Get tweets from a list

```python
twitter_get_list_tweets(list_id="84839422", max_results=10)
```

## Search Query Operators

| Operator | Example | Meaning |
|----------|---------|---------|
| `from:` | `from:nasa` | Tweets by a specific user |
| `to:` | `to:support` | Replies to a specific user |
| `-is:retweet` | `-is:retweet` | Exclude retweets |
| `has:media` | `has:media` | Tweets with media |
| `lang:` | `lang:en` | Filter by language |
| `#` | `#python` | Hashtag search |

## Error Handling

All tools return error dicts on failure:

```python
{"error": "X_BEARER_TOKEN is required", "help": "Set X_BEARER_TOKEN environment variable"}
{"error": "HTTP 429: ..."}
{"error": "tweet_id is required"}
```
