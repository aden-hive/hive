"""
Cloudinary credentials.

Contains credentials for Cloudinary image/video management.
Requires CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.
"""

from .base import CredentialSpec

CLOUDINARY_CREDENTIALS = {
    "cloudinary_cloud_name": CredentialSpec(
        env_var="CLOUDINARY_CLOUD_NAME",
        tools=[
            "cloudinary_upload",
            "cloudinary_list_resources",
            "cloudinary_get_resource",
            "cloudinary_delete_resource",
            "cloudinary_search",
            "cloudinary_get_usage",
            "cloudinary_rename_resource",
            "cloudinary_add_tag",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloudinary.com/",
        description="Cloudinary cloud name from your dashboard",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Cloudinary access:
1. Go to https://console.cloudinary.com/
2. Copy your Cloud Name, API Key, and API Secret from the dashboard
3. Set environment variables:
   export CLOUDINARY_CLOUD_NAME=your-cloud-name
   export CLOUDINARY_API_KEY=your-api-key
   export CLOUDINARY_API_SECRET=your-api-secret""",
        health_check_endpoint="",
        credential_id="cloudinary_cloud_name",
        credential_key="api_key",
    ),
    "cloudinary_key": CredentialSpec(
        env_var="CLOUDINARY_API_KEY",
        tools=[
            "cloudinary_upload",
            "cloudinary_list_resources",
            "cloudinary_get_resource",
            "cloudinary_delete_resource",
            "cloudinary_search",
            "cloudinary_get_usage",
            "cloudinary_rename_resource",
            "cloudinary_add_tag",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloudinary.com/",
        description="Cloudinary API key for authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See CLOUDINARY_CLOUD_NAME instructions above.""",
        health_check_endpoint="",
        credential_id="cloudinary_key",
        credential_key="api_key",
    ),
    "cloudinary_secret": CredentialSpec(
        env_var="CLOUDINARY_API_SECRET",
        tools=[
            "cloudinary_upload",
            "cloudinary_list_resources",
            "cloudinary_get_resource",
            "cloudinary_delete_resource",
            "cloudinary_search",
            "cloudinary_get_usage",
            "cloudinary_rename_resource",
            "cloudinary_add_tag",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloudinary.com/",
        description="Cloudinary API secret for authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See CLOUDINARY_CLOUD_NAME instructions above.""",
        health_check_endpoint="",
        credential_id="cloudinary_secret",
        credential_key="api_key",
    ),
}
