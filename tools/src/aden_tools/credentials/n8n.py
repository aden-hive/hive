"""
n8n workflow automation credentials.

Contains credentials for the n8n REST API v1.
Requires N8N_API_KEY and N8N_BASE_URL.
"""

from .base import CredentialSpec

N8N_CREDENTIALS = {
    "n8n": CredentialSpec(
        env_var="N8N_API_KEY",
        tools=[
            "n8n_list_workflows",
            "n8n_get_workflow",
            "n8n_activate_workflow",
            "n8n_deactivate_workflow",
            "n8n_list_executions",
            "n8n_get_execution",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.n8n.io/api/authentication/",
        description="n8n API key for workflow management",
        direct_api_key_supported=True,
        api_key_instructions="""To set up n8n API access:
1. In n8n, go to Settings > API
2. Generate an API key
3. Set environment variables:
   export N8N_API_KEY=your-api-key
   export N8N_BASE_URL=https://your-n8n-instance.com""",
        health_check_endpoint="",
        credential_id="n8n",
        credential_key="api_key",
    ),
    "n8n_base_url": CredentialSpec(
        env_var="N8N_BASE_URL",
        tools=[
            "n8n_list_workflows",
            "n8n_get_workflow",
            "n8n_activate_workflow",
            "n8n_deactivate_workflow",
            "n8n_list_executions",
            "n8n_get_execution",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.n8n.io/api/",
        description="n8n instance base URL (e.g. 'https://your-n8n.example.com')",
        direct_api_key_supported=True,
        api_key_instructions="""See N8N_API_KEY instructions above.""",
        health_check_endpoint="",
        credential_id="n8n_base_url",
        credential_key="api_key",
    ),
}
