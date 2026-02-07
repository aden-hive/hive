"""
Reddit tool credentials.

Contains credentials for Reddit API integration using OAuth 2.0.
"""

from .base import CredentialSpec

REDDIT_CREDENTIALS = {
    "reddit": CredentialSpec(
        env_var="REDDIT_CREDENTIALS",
        tools=[
            # Search & Monitoring
            "reddit_search_posts",
            "reddit_search_comments",
            "reddit_get_subreddit_new",
            "reddit_get_subreddit_hot",
            "reddit_get_post",
            "reddit_get_comments",
            # Content Creation
            "reddit_submit_post",
            "reddit_reply_to_post",
            "reddit_reply_to_comment",
            "reddit_edit_comment",
            "reddit_delete_comment",
            # User Engagement
            "reddit_get_user_profile",
            "reddit_upvote",
            "reddit_downvote",
            "reddit_save_post",
            # Moderation
            "reddit_remove_post",
            "reddit_approve_post",
            "reddit_ban_user",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.reddit.com/prefs/apps",
        description="Reddit API credentials (JSON object with OAuth 2.0 tokens)",
        # Auth method support
        aden_supported=False,  # Future OAuth support
        aden_provider_name="reddit",
        direct_api_key_supported=True,
        api_key_instructions="""To get Reddit API credentials:
1. Go to https://www.reddit.com/prefs/apps
2. Click "create another app..." at the bottom
3. Fill in the details:
   - Name: Your app name
   - App type: Select "script" for personal use or "web app" for production
   - Description: Brief description of your app
   - About URL: Optional URL
   - Redirect URI: http://localhost:8080 (for script type)
4. Click "create app"
5. Note your credentials:
   - client_id: The string under "personal use script"
   - client_secret: The "secret" value
6. Generate a refresh token:
   - For script apps: Use your Reddit username and password
   - For web apps: Implement OAuth2 flow
7. Set the environment variable as JSON:
   export REDDIT_CREDENTIALS='{"client_id":"YOUR_CLIENT_ID",\
"client_secret":"YOUR_SECRET","refresh_token":"YOUR_REFRESH_TOKEN",\
"user_agent":"YOUR_APP_NAME/1.0"}'

Required scopes: read, submit, vote, identity
Optional scopes (for moderation): modposts""",
        # Health check configuration
        health_check_endpoint="https://oauth.reddit.com/api/v1/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="reddit",
        credential_key="credentials",  # JSON object with all fields
    ),
}
