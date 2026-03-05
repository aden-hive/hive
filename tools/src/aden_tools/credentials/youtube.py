"""
YouTube Data API credentials.

Contains credentials for YouTube Data API v3 integration.
"""

from .base import CredentialSpec

YOUTUBE_CREDENTIALS = {
    "youtube": CredentialSpec(
        env_var="YOUTUBE_API_KEY",
        tools=[
            "youtube_search_videos",
            "youtube_get_video_details",
            "youtube_get_channel",
            "youtube_list_channel_videos",
            "youtube_get_playlist",
            "youtube_search_channels",
            "youtube_get_video_comments",
            "youtube_get_video_categories",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google API key with YouTube Data API v3 enabled",
        direct_api_key_supported=True,
        api_key_instructions="""To get a YouTube Data API key:
1. Go to https://console.cloud.google.com/
2. Create a new project or select an existing one
3. Go to APIs & Services > Library
4. Search for "YouTube Data API v3" and enable it
5. Go to APIs & Services > Credentials
6. Click "Create Credentials" > "API key"
7. Copy the API key
8. (Optional) Restrict the key to YouTube Data API v3 only""",
        health_check_endpoint="https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode=US",
        credential_id="youtube",
        credential_key="api_key",
    ),
}
