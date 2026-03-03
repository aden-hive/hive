"""
Plaid Credential Management

Hive v0.6+ compatible credential helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from framework.credentials import CredentialStore


@dataclass
class PlaidCredentials:
    """Plaid API authentication credentials."""

    client_id: str
    secret: str
    environment: str = "sandbox"
    access_token: Optional[str] = None
    public_token: Optional[str] = None

    @classmethod
    def from_credential_store(
        cls,
        store: CredentialStore,
        credential_ref: str = "plaid/default",
    ) -> "PlaidCredentials":
        """Load credentials from Hive v0.6+ credential store."""
        cred = store.get_credential(credential_ref)
        if cred is None:
            raise ValueError(f"Plaid credential not found: {credential_ref}")

        client_id = cred.get_key("client_id")
        secret = cred.get_key("secret")
        environment = cred.get_key("environment") or "sandbox"
        access_token = cred.get_key("access_token")
        public_token = cred.get_key("public_token")

        if not client_id or not secret:
            raise ValueError(
                f"Plaid credential '{credential_ref}' is missing required keys: client_id, secret"
            )

        return cls(
            client_id=client_id,
            secret=secret,
            environment=environment,
            access_token=access_token,
            public_token=public_token,
        )


PLAID_CREDENTIAL_SPEC = {
    "type": "object",
    "required": ["client_id", "secret"],
    "properties": {
        "client_id": {
            "type": "string",
            "description": "Plaid client ID",
        },
        "secret": {
            "type": "string",
            "description": "Plaid secret key",
            "sensitive": True,
        },
        "environment": {
            "type": "string",
            "enum": ["sandbox", "development", "production"],
            "default": "sandbox",
            "description": "Plaid environment",
        },
        "access_token": {
            "type": "string",
            "description": "Plaid access token (obtained after account linking)",
            "sensitive": True,
        },
        "public_token": {
            "type": "string",
            "description": "Temporary public token for account linking",
            "sensitive": True,
        },
    },
}
