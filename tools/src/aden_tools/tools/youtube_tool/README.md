# YouTube Data API Tool

Search and retrieve video/channel information from YouTube.

## Description

Provides comprehensive access to YouTube's public data including video search, channel statistics, playlists, and detailed metadata. Use when you need to find YouTube content, analyze video statistics, or retrieve channel information.

## Tools (6)

| Tool | Description |
|------|-------------|
| `youtube_search_videos` | Search for videos by query with sorting options |
| `youtube_get_video_details` | Get detailed information about a specific video |
| `youtube_get_channel_info` | Get channel statistics and information |
| `youtube_list_channel_videos` | List videos from a specific channel |
| `youtube_get_playlist_items` | Get videos from a playlist |
| `youtube_search_channels` | Search for channels by query |

## Setup

Requires a YouTube Data API v3 key from [Google Cloud Console](https://console.cloud.google.com/apis/credentials).

### Steps:
1. Create a project in Google Cloud Console
2. Enable YouTube Data API v3
3. Create an API key
4. Set the `YOUTUBE_API_KEY` environment variable

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 key from Google Cloud Console |

## Parameters

### `youtube_search_videos`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | - | Search query string |
| `max_results` | `int` | `10` | Number of results (1-50) |
| `order` | `str` | `"relevance"` | Sort order: date, rating, relevance, title, viewCount |

### `youtube_get_video_details`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_id` | `str` | - | YouTube video ID (e.g., "dQw4w9WgXcQ") |

### `youtube_get_channel_info`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel_id` | `str` | - | YouTube channel ID |

### `youtube_list_channel_videos`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel_id` | `str` | - | YouTube channel ID |
| `max_results` | `int` | `10` | Number of results (1-50) |
| `order` | `str` | `"date"` | Sort order: date, rating, relevance, title, viewCount |

### `youtube_get_playlist_items`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `playlist_id` | `str` | - | YouTube playlist ID |
| `max_results` | `int` | `10` | Number of results (1-50) |

### `youtube_search_channels`
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | - | Search query string |
| `max_results` | `int` | `10` | Number of results (1-50) |

## Example Usage

```python
# Search for videos
youtube_search_videos(
    query="Python tutorial",
    max_results=5,
    order="viewCount"
)

# Get video details
youtube_get_video_details(video_id="dQw4w9WgXcQ")

# Search for a channel, then list its videos (tool chaining)
channels = youtube_search_channels(query="Fireship", max_results=1)
channel_id = channels["items"][0]["id"]["channelId"]

videos = youtube_list_channel_videos(
    channel_id=channel_id,
    max_results=20,
    order="date"
)

# Get channel statistics
youtube_get_channel_info(channel_id="UCsBjURrPoezykLs9EqgamOA")

# Get playlist videos
youtube_get_playlist_items(
    playlist_id="PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
    max_results=25
)
```

## Response Format

All tools return JSON responses following YouTube Data API v3 schema:

- **Search results**: Contains `items` array with video/channel data
- **Video details**: Includes `snippet`, `statistics`, and `contentDetails`
- **Channel info**: Includes `snippet`, `statistics`, and `contentDetails`
- **Errors**: Returns `{"error": "message", "help": "..."}`

## API Quota

YouTube Data API v3 has daily quota limits (10,000 units/day default). Each operation costs different units:
- Search: 100 units
- Video details: 1 unit
- Channel info: 1 unit
- Playlist items: 1 unit

Monitor usage in [Google Cloud Console](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas).

## Reference

- [YouTube Data API v3 Documentation](https://developers.google.com/youtube/v3/docs)
- [API Key Setup Guide](https://developers.google.com/youtube/registering_an_application)
- [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
