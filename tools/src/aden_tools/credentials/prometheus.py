from __future__ import annotations

from .base import CredentialSpec

PROMETHEUS_CREDENTIALS = {
    "prometheus": CredentialSpec(
        env_var="PROMETHEUS_BASE_URL",
        tools=[
            "prometheus_query",
            "prometheus_query_range",
        ],
        required=True,
        startup_required=False,
        help_url="https://prometheus.io/docs/prometheus/latest/querying/api/",
        description="Base URL of Prometheus server",
        aden_supported=False,
        direct_api_key_supported=False,
        api_key_instructions="""To configure Prometheus access:

1. Set your Prometheus base URL:
   export PROMETHEUS_BASE_URL=http://localhost:9090

Optional authentication:

2. For Bearer Token:
   export PROMETHEUS_TOKEN=your-token

3. For Basic Auth:
   export PROMETHEUS_USERNAME=admin
   export PROMETHEUS_PASSWORD=secret

Notes:
- PROMETHEUS_BASE_URL is required
- Authentication is optional (most local setups don’t need it)
""",
        health_check_endpoint="/api/v1/query?query=up",
        health_check_method="GET",
        credential_id="prometheus",
        credential_key="base_url",
    ),
}
