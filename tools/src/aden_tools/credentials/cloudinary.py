"""
Cloudinary tool credentials.

Contains credentials for Cloudinary API integration.
"""

from .base import CredentialSpec

CLOUDINARY_CREDENTIALS = {
    "cloudinary": CredentialSpec(
        env_var="CLOUDINARY_URL",
        tools=[
            "cloudinary_upload",
            "cloudinary_transform",
            "cloudinary_get_asset",
            "cloudinary_delete",
            "cloudinary_list_assets",
        ],
        required=True,
        startup_required=False,
        help_url="https://cloudinary.com/documentation/how_to_integrate_cloudinary",
        description="Cloudinary URL (cloudinary://api_key:api_secret@cloud_name)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Cloudinary URL:
1. Log in to your Cloudinary Console (https://cloudinary.com/console)
2. In the Dashboard, you'll see your "API Environment variable"
3. Copy the URL starting with "cloudinary://"
4. Use this full URL as your CLOUDINARY_URL environment variable.""",
        # Health check configuration
        health_check_endpoint=None,
        # Credential store mapping
        credential_id="cloudinary",
        credential_key="url",
    ),
}
