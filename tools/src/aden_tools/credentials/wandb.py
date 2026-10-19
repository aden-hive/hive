"""
Weights & Biases integration credentials.

Contains credentials for the W&B GraphQL API.
Requires WANDB_API_KEY only — no host configuration needed.
"""

from __future__ import annotations

from .base import CredentialSpec

WANDB_CREDENTIALS = {
    "wandb_api_key": CredentialSpec(
        env_var="WANDB_API_KEY",
        tools=[
            "wandb_list_projects",
            "wandb_list_runs",
            "wandb_get_run",
            "wandb_get_run_metrics",
            "wandb_list_artifacts",
            "wandb_get_summary",
        ],
        required=True,
        startup_required=False,
        help_url="https://wandb.ai/authorize",
        description="Weights & Biases API Key",
        direct_api_key_supported=True,
        api_key_instructions="""To set up W&B API access:
1. Create a W&B account at https://wandb.ai
2. Go to https://wandb.ai/authorize
3. Copy your API key
4. Set environment variable:
   export WANDB_API_KEY=your-api-key""",
        health_check_endpoint="",
        credential_id="wandb_api_key",
        credential_key="api_key",
    ),
}
