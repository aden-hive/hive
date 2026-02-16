"""ArXiv tool credentials.

Contains metadata for the public ArXiv API integration.
"""

from .base import CredentialSpec

ARXIV_CREDENTIALS = {
    "arxiv_public": CredentialSpec(
        env_var="N/A",  # Public API
        tools=[
            "arxiv_search_papers",
            "arxiv_download_paper",
        ],
        required=False,
        startup_required=False,
        help_url="https://arxiv.org/help/api/user-manual",
        description="Public Access (No Token Required)",
        direct_api_key_supported=False,
        health_check_endpoint="https://export.arxiv.org/api/query?search_query=all:test&start=0&max_results=1",
        health_check_method="GET",
        credential_id="arxiv_public",
    ),
}
