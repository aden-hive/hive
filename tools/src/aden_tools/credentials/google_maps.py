"""
Google Maps Platform tool credentials.

Contains credentials for Google Maps API integration
(Geocoding, Directions, Distance Matrix, Places).
"""

from .base import CredentialSpec

GOOGLE_MAPS_CREDENTIALS = {
    "google_maps": CredentialSpec(
        env_var="GOOGLE_MAPS_API_KEY",
        tools=[
            "maps_geocode",
            "maps_reverse_geocode",
            "maps_directions",
            "maps_distance_matrix",
            "maps_place_details",
            "maps_place_search",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="API key for Google Maps Platform (Geocoding, Directions, Places)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Google Maps API key:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create a new project (or select an existing one)
3. Enable the following APIs from the API Library:
   - Geocoding API
   - Directions API
   - Distance Matrix API
   - Places API
4. Go to Credentials > Create Credentials > API Key
5. Copy the generated API key
6. (Recommended) Click "Restrict Key" and limit it to the above APIs
7. Store the key securely

Note: Google provides $200/month in free credits (~40,000 geocoding requests).""",
        # Health check configuration
        health_check_endpoint="https://maps.googleapis.com/maps/api/geocode/json",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_maps",
        credential_key="api_key",
    ),
}
