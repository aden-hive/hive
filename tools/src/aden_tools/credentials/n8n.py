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
    # n8n_trigger_webhook uses a self-contained webhook URL — no API key needed.
    # This entry exists so the tool appears in the credential registry and
    # help text is surfaced to users who need to locate their webhook URL.
    "n8n_webhook": CredentialSpec(
        env_var="N8N_WEBHOOK_URL",
        tools=["n8n_trigger_webhook"],
        required=False,
        startup_required=False,
        help_url="https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/",
        description="n8n webhook URL — obtained from the Webhook node in the workflow editor",
        direct_api_key_supported=True,
        api_key_instructions="""To get the webhook URL:
1. Open your workflow in the n8n editor
2. Add or click an existing Webhook node
3. Copy the 'Webhook URL' shown in the node panel
4. Pass it directly as the webhook_url parameter to n8n_trigger_webhook""",
        health_check_endpoint="",
        credential_id="n8n_webhook",
        credential_key="api_key",
    ),
}
