"""YouTube Data API credentials."""

from .base import CredentialSpec

YOUTUBE_CREDENTIALS = {
    "youtube": CredentialSpec(
        env_var="YOUTUBE_API_KEY",
        tools=[
            "youtube_search_videos",
            "youtube_get_video_details",
            "youtube_get_channel_info",
            "youtube_list_channel_videos",
            "youtube_get_playlist_items",
            "youtube_search_channels",
        ],
        help_url="https://console.cloud.google.com/apis/credentials",
        description="YouTube Data API v3 key",
    ),
}
