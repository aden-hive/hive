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
        direct_api_key_supported=True,
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
        health_check_endpoint="/-/ready",
        health_check_method="GET",
        credential_id="prometheus",
        credential_key="base_url",
    ),
    "prometheus_token": CredentialSpec(
        env_var="PROMETHEUS_TOKEN",
        tools=[
            "prometheus_query",
            "prometheus_query_range",
        ],
        required=False,
        startup_required=False,
        help_url="https://prometheus.io/docs/prometheus/latest/querying/api/",
        description="Optional Bearer token for Prometheus authentication",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Optional: set a bearer token for authenticated Prometheus instances:

export PROMETHEUS_TOKEN=your-token
""",
        health_check_endpoint="",
        credential_id="prometheus_token",
        credential_key="api_key",
    ),
    "prometheus_username": CredentialSpec(
        env_var="PROMETHEUS_USERNAME",
        tools=[
            "prometheus_query",
            "prometheus_query_range",
        ],
        required=False,
        startup_required=False,
        help_url="https://prometheus.io/docs/prometheus/latest/querying/api/",
        description="Optional username for basic auth",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Optional: set username for basic authentication:

export PROMETHEUS_USERNAME=admin
""",
        health_check_endpoint="",
        credential_id="prometheus_username",
        credential_key="username",
    ),
    "prometheus_password": CredentialSpec(
        env_var="PROMETHEUS_PASSWORD",
        tools=[
            "prometheus_query",
            "prometheus_query_range",
        ],
        required=False,
        startup_required=False,
        help_url="https://prometheus.io/docs/prometheus/latest/querying/api/",
        description="Optional password for basic auth",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Optional: set password for basic authentication:

export PROMETHEUS_PASSWORD=secret
""",
        health_check_endpoint="",
        credential_id="prometheus_password",
        credential_key="password",
    ),
}
