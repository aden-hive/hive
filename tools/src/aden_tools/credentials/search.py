"""
Search tool credentials.

Contains credentials for search providers like Brave Search, Google, Bing, etc.
"""

from .base import CredentialSpec

SEARCH_CREDENTIALS = {
    "brave_search": CredentialSpec(
        env_var="BRAVE_SEARCH_API_KEY",
        tools=["web_search"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://brave.com/search/api/",
        description="API key for Brave Search",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get a Brave Search API key:
1. Go to https://brave.com/search/api/
2. Create a Brave Search API account (or sign in)
3. Choose a plan (Free tier includes 2,000 queries/month)
4. Navigate to the API Keys section in your dashboard
5. Click "Create API Key" and give it a name
6. Copy the API key and store it securely""",
        # Health check configuration
        health_check_endpoint="https://api.search.brave.com/res/v1/web/search",
        # Credential store mapping
        credential_id="brave_search",
        credential_key="api_key",
    ),
    "google_search": CredentialSpec(
        env_var="GOOGLE_API_KEY",
        tools=["google_search"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="API key for Google Custom Search",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get a Google Custom Search API key:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create a new project (or select an existing one)
3. Enable the "Custom Search API" from the API Library
4. Go to Credentials > Create Credentials > API Key
5. Copy the generated API key
6. (Recommended) Click "Restrict Key" and limit it to the Custom Search API
7. Store the key securely""",
        # Health check configuration
        health_check_endpoint="https://www.googleapis.com/customsearch/v1",
        # Credential store mapping
        credential_id="google_search",
        credential_key="api_key",
        credential_group="google_custom_search",
    ),
    "google_cse": CredentialSpec(
        env_var="GOOGLE_CSE_ID",
        tools=["google_search"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://programmablesearchengine.google.com/controlpanel/all",
        description="Google Custom Search Engine ID",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get a Google Custom Search Engine (CSE) ID:
1. Go to https://programmablesearchengine.google.com/controlpanel/all
2. Click "Add" to create a new search engine
3. Under "What to search", select "Search the entire web"
4. Give your search engine a name (e.g., "Hive Agent Search")
5. Click "Create"
6. Copy the Search Engine ID (cx value) from the overview page""",
        # Health check configuration
        health_check_endpoint="https://www.googleapis.com/customsearch/v1",
        # Credential store mapping
        credential_id="google_cse",
        credential_key="api_key",
        credential_group="google_custom_search",
    ),
}
