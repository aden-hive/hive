"""
OpenRouter credential spec.

Registers OPENROUTER_API_KEY with the Hive credential store so agents
can call CredentialStoreAdapter.get("openrouter") without a KeyError.

Get a free API key at: https://openrouter.ai/keys
"""

from .base import CredentialSpec

OPENROUTER_CREDENTIALS = {
    "openrouter": CredentialSpec(
        env_var="OPENROUTER_API_KEY",
        tools=[],  # openrouter_agent reads the key directly
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://openrouter.ai/keys",
        description="API key for OpenRouter — free access to open-source models",
        direct_api_key_supported=True,
        api_key_instructions="""\
To get an OpenRouter API key:
1. Go to https://openrouter.ai/keys
2. Create a free account (no credit card required)
3. Click "Create key" and copy the key
4. Run: export OPENROUTER_API_KEY=sk-or-v1-...
   Or set it via: hive setup-credentials""",
        health_check_endpoint="https://openrouter.ai/api/v1/models",
        credential_id="openrouter",
        credential_key="api_key",
    ),
}
