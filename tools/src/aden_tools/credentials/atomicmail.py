"""
Atomic Mail tool credentials.
Contains credentials for Atomic Mail, an email inbox owned by the agent itself.
"""

from .base import CredentialSpec

ATOMICMAIL_CREDENTIALS = {
    "atomicmail": CredentialSpec(
        env_var="ATOMIC_MAIL_API_KEY",
        tools=[
            "atomicmail_get_address",
            "atomicmail_send",
            "atomicmail_list_emails",
            "atomicmail_read_email",
            "atomicmail_search",
            "atomicmail_reply",
            "atomicmail_mark_read",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.atomicmail.ai",
        description="Atomic Mail inbox API key: gives the agent its own @atomicmail.ai mailbox",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an Atomic Mail API key:
1. Follow the quickstart at https://docs.atomicmail.ai to register an agent inbox
   (registration is free and needs no domain, card or email confirmation)
2. Registration returns an API key for that inbox; copy it
3. Set it as ATOMIC_MAIL_API_KEY
Note: the key is exchanged for short-lived tokens via a proof-of-work step, so the
first call after start-up can take a few seconds.""",
        # The key is validated by logging in (PoW + session exchange); see
        # AtomicMailHealthChecker. There is no cheaper key-only endpoint.
        health_check_endpoint="https://auth.atomicmail.ai/api/v1/session",
        health_check_method="POST",
        credential_id="atomicmail",
        credential_key="api_key",
    ),
}
