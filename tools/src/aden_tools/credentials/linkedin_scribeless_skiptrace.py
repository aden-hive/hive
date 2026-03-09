"""Credential specs for LinkedIn, Scribeless, and Skip Trace tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialSpec

CREDENTIAL_SPECS: dict[str, CredentialSpec] = {
    "linkedin": CredentialSpec(
        env_var="LINKEDIN_COOKIE",
        tools=[
            "linkedin_scrape_profiles",
            "linkedin_send_connection",
            "linkedin_validate_url",
        ],
        direct_api_key_supported=True,
        description="LinkedIn session cookie for browser automation",
        help_text="Get your LinkedIn session cookie (li_at value) from browser DevTools",
        help_url="https://www.linkedin.com/",
    ),
    "scribeless": CredentialSpec(
        env_var="SCRIBELESS_API_KEY",
        tools=[
            "scribeless_send_letter",
            "scribeless_get_status",
            "scribeless_get_balance",
        ],
        direct_api_key_supported=True,
        description="Scribeless API key for sending handwritten letters",
        help_text="Get your API key at https://scribeless.org/dashboard/api",
        help_url="https://scribeless.org/docs",
    ),
    "skiptrace": CredentialSpec(
        env_var="SKIPTRACE_API_KEY",
        tools=[
            "skiptrace_lookup",
            "skiptrace_batch_lookup",
            "skiptrace_parse_csv",
        ],
        direct_api_key_supported=True,
        description="Skip Trace API key for mailing address lookup",
        help_text="Sign up at https://skiptrace.io for API access",
        help_url="https://skiptrace.io/docs",
    ),
}
