# Reddit Tool

Community management and content monitoring tool for Reddit. Monitor brand mentions, engage with communities, and automate content posting across Reddit's 430M+ monthly active users and 100K+ communities.

## Features

### Search & Monitoring (6 functions)
- **reddit_search_posts**: Search for posts matching keywords
- **reddit_search_comments**: Search for comments (via post search + comment retrieval)
- **reddit_get_subreddit_posts**: Get hot/new/top posts from a subreddit
- **reddit_get_post**: Retrieve specific post details
- **reddit_get_post_comments**: Get all comments from a post
- **reddit_get_user_posts**: Monitor user posting activity

### Content Creation (5 functions)
- **reddit_submit_post**: Create text or link posts
- **reddit_reply_to_post**: Reply to posts
- **reddit_reply_to_comment**: Reply to comments
- **reddit_edit_comment**: Edit your comments
- **reddit_delete_comment**: Remove your comments

### User Engagement (4 functions)
- **reddit_get_user_profile**: View user profiles and karma
- **reddit_vote**: Upvote/downvote posts and comments
- **reddit_save_post**: Bookmark posts
- **reddit_unsave_post**: Remove bookmarks

### Moderation (3 functions - requires moderator permissions)
- **reddit_remove_post**: Remove posts as a moderator
- **reddit_approve_post**: Approve posts from moderation queue
- **reddit_ban_user**: Ban users from a subreddit

## Setup

### 1. Create a Reddit App

1. Go to https://www.reddit.com/prefs/apps
2. Click "create another app..." at the bottom
3. Fill in the details:
   - **Name**: Your app name (e.g., "My Bot v1.0")
   - **App type**: Select "script" for personal use
   - **Description**: Brief description
   - **Redirect URI**: http://localhost:8080
4. Click "create app"

### 2. Get Your Credentials

After creating the app, you'll see:
- **client_id**: The string under "personal use script" (looks like: `abc123xyz`)
- **client_secret**: The "secret" value (looks like: `abc123xyz...`)

### 3. Generate a Refresh Token

For script-type apps, you can use your Reddit username and password. The PRAW library handles this automatically.

### 4. Set Environment Variable

Set the `REDDIT_CREDENTIALS` environment variable as a JSON object:

```bash
export REDDIT_CREDENTIALS='{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_SECRET",
  "refresh_token": "YOUR_REFRESH_TOKEN",
  "user_agent": "MyApp/1.0"
}'
```

Or for Windows:
```powershell
$env:REDDIT_CREDENTIALS='{"client_id":"YOUR_CLIENT_ID","client_secret":"YOUR_SECRET","refresh_token":"YOUR_REFRESH_TOKEN","user_agent":"MyApp/1.0"}'
```

## Usage Examples

### Search for Brand Mentions

```python
# Search for posts mentioning your brand
result = reddit_search_posts(
    query="YourBrand",
    subreddit="all",
    time_filter="day",
    sort="new",
    limit=50
)

for post in result["posts"]:
    print(f"Post: {post['title']}")
    print(f"Subreddit: r/{post['subreddit']}")
    print(f"Score: {post['score']}")
    print(f"URL: {post['permalink']}")
```

### Monitor a Subreddit

```python
# Get hot posts from a specific subreddit
result = reddit_get_subreddit_posts(
    subreddit="python",
    feed_type="hot",
    limit=25
)

for post in result["posts"]:
    print(f"{post['title']} ({post['score']} points)")
```

### Engage with Posts

```python
# Reply to a post
result = reddit_reply_to_post(
    post_id="abc123",
    text="Great question! Here's my answer..."
)

# Upvote the post
reddit_vote(item_id="abc123", direction="up")
```

### Create Content

```python
# Submit a text post
result = reddit_submit_post(
    subreddit="test",
    title="Test Post Title",
    content="This is the post body text.",
)

print(f"Post created: {result['permalink']}")
```

### Track Discussions

```python
# Get all comments from a post
result = reddit_get_post_comments(
    post_id="abc123",
    sort="best",
    limit=100
)

for comment in result["comments"]:
    print(f"{comment['author']}: {comment['body'][:100]}")
```

## Function Reference

### reddit_search_posts

Search for Reddit posts matching a query.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| query | str | Required | Search query (1-512 characters) |
| subreddit | str | "all" | Subreddit name or "all" for site-wide |
| time_filter | str | "all" | "hour", "day", "week", "month", "year", "all" |
| sort | str | "relevance" | "relevance", "hot", "top", "new", "comments" |
| limit | int | 10 | Maximum posts to return (1-100) |

**Returns:** Dict with `query`, `subreddit`, `count`, and `posts` array

### reddit_get_subreddit_posts

Get posts from a subreddit feed.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| subreddit | str | Required | Subreddit name (e.g., "python") |
| feed_type | str | "hot" | "hot", "new", "top", "rising", "controversial" |
| time_filter | str | "all" | Time period for "top"/"controversial" |
| limit | int | 25 | Maximum posts to return (1-100) |

**Returns:** Dict with `subreddit`, `feed_type`, `count`, and `posts` array

### reddit_get_post

Get a specific Reddit post by ID.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| post_id | str | Required | Reddit post ID (e.g., "abc123") |

**Returns:** Dict with `success` and `post` object

### reddit_get_post_comments

Get comments from a Reddit post.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| post_id | str | Required | Reddit post ID |
| sort | str | "best" | "best", "top", "new", "controversial", "old", "qa" |
| limit | int | 50 | Maximum comments to return (1-500) |

**Returns:** Dict with `post_id`, `count`, and `comments` array

### reddit_submit_post

Submit a new post to a subreddit.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| subreddit | str | Required | Subreddit name to post to |
| title | str | Required | Post title (1-300 characters) |
| content | str | "" | Post body text (for self posts) |
| url | str | "" | Link URL (for link posts) |
| flair_id | str | "" | Optional flair ID |

**Returns:** Dict with `success`, `post_id`, `permalink`, and `post` object

### reddit_reply_to_post

Reply to a Reddit post.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| post_id | str | Required | Reddit post ID to reply to |
| text | str | Required | Reply text (1-10000 characters) |

**Returns:** Dict with `success`, `comment_id`, and `permalink`

### reddit_vote

Vote on a post or comment.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| item_id | str | Required | Reddit post or comment ID |
| direction | str | Required | "up" (upvote), "down" (downvote), "clear" |

**Returns:** Dict with `success`, `item_id`, `direction`, and `message`

### reddit_get_user_profile

Get a Reddit user's profile information.

**Arguments:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| username | str | Required | Reddit username (without u/ prefix) |

**Returns:** Dict with `success` and `user` object containing karma, account age, etc.

## API Limits

- **Rate Limit**: 60 requests per minute (completely free tier)
- **No usage costs**: Reddit API is completely free to use

## OAuth Scopes

The tool requires these OAuth scopes:
- **read**: View Reddit content
- **submit**: Submit posts and comments
- **vote**: Upvote and downvote content
- **identity**: Access Reddit account information
- **modposts** (optional): Moderate posts if you're a moderator

## Error Handling

All functions return a dict. Check for `error` key to detect failures:

```python
result = reddit_search_posts(query="test")

if "error" in result:
    print(f"Error: {result['error']}")
    if "help" in result:
        print(f"Help: {result['help']}")
else:
    print(f"Found {result['count']} posts")
```

## Troubleshooting

### "REDDIT_CREDENTIALS not configured"

Make sure you've set the `REDDIT_CREDENTIALS` environment variable with all required fields.

### "Invalid or expired Reddit token"

Your refresh token may have expired. Generate a new one at https://www.reddit.com/prefs/apps

### "Forbidden - check token permissions or rate limit"

Either:
1. You've hit the rate limit (60 requests/minute)
2. Your app doesn't have the required OAuth scopes
3. You're trying to access private content

### "Resource not found"

The post, comment, or user you're trying to access doesn't exist or was deleted.

## Dependencies

- **praw** >=7.7.1 - Python Reddit API Wrapper
- **prawcore** >=2.4.0 - Core functionality for PRAW

## Health Check

The tool performs health checks at: `https://oauth.reddit.com/api/v1/me`

This validates your credentials and ensures you can authenticate with Reddit.

## References

- [Reddit API Documentation](https://www.reddit.com/dev/api/)
- [PRAW Documentation](https://praw.readthedocs.io/)
- [Reddit Apps Page](https://www.reddit.com/prefs/apps)
- [Reddit OAuth2 Quick Start](https://github.com/reddit-archive/reddit/wiki/OAuth2-Quick-Start-Example)
