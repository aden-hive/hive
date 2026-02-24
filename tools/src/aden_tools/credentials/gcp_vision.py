"""
GCP Vision tool credentials.

Contains credentials for Google Cloud Vision API integration.
"""

from .base import CredentialSpec

GCP_VISION_CREDENTIALS = {
    "google_vision": CredentialSpec(
        env_var="GOOGLE_CLOUD_VISION_API_KEY",
        tools=[
            "vision_detect_labels",
            "vision_detect_text",
            "vision_detect_faces",
            "vision_localize_objects",
            "vision_detect_logos",
            "vision_detect_landmarks",
            "vision_image_properties",
            "vision_web_detection",
            "vision_safe_search",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google Cloud Vision API key for image analysis",
        # Auth method support
        aden_supported=False,
        aden_provider_name="",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Google Cloud Vision API key:
1. Go to Google Cloud Console (console.cloud.google.com)
2. Create a new project or select existing
3. Go to APIs & Services > Library
4. Search for "Cloud Vision API" and enable it
5. Go to APIs & Services > Credentials
6. Click "Create Credentials" > "API Key"
7. Copy the API key""",
        # Health check configuration
        health_check_endpoint="",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_vision",
        credential_key="api_key",
    ),
}
