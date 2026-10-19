"""
Obsidian Local REST API credentials.

Contains credentials for the Obsidian Local REST API plugin.
Requires OBSIDIAN_REST_API_KEY. Optional OBSIDIAN_REST_BASE_URL.
"""

from .base import CredentialSpec

OBSIDIAN_CREDENTIALS = {
    "obsidian": CredentialSpec(
        env_var="OBSIDIAN_REST_API_KEY",
        tools=[
            "obsidian_read_note",
            "obsidian_write_note",
            "obsidian_append_note",
            "obsidian_search",
            "obsidian_list_files",
            "obsidian_get_active",
        ],
        required=True,
        startup_required=False,
        help_url="https://github.com/coddingtonbear/obsidian-local-rest-api",
        description="Obsidian Local REST API key (64-char hex, from plugin settings)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Obsidian Local REST API access:
1. Install the 'Local REST API' community plugin in Obsidian
2. Enable the plugin and go to its settings
3. Copy the API Key (64-character hex string)
4. Set environment variables:
   export OBSIDIAN_REST_API_KEY=your-api-key
   export OBSIDIAN_REST_BASE_URL=https://127.0.0.1:27124 (optional)""",
        health_check_endpoint="",
        credential_id="obsidian",
        credential_key="api_key",
    ),
}
