"""
SAP S/4HANA Credential Management

Follows Hive's credentialSpec pattern for secure authentication.
"""

from __future__ import annotations

from dataclasses import dataclass

from framework.credentials import CredentialStore


@dataclass
class SAPCredentials:
    """SAP S/4HANA authentication credentials."""
    base_url: str
    username: str
    password: str
    client: str = "100"
    verify_ssl: bool = True
    
    @classmethod
    def from_credential_store(
        cls,
        store: CredentialStore,
        credential_ref: str = "sap_s4hana/default",
    ) -> "SAPCredentials":
        """Load credentials from Hive v0.6+ credential store."""
        cred = store.get_credential(credential_ref)
        if cred is None:
            raise ValueError(f"SAP credential not found: {credential_ref}")

        base_url = cred.get_key("base_url")
        username = cred.get_key("username")
        password = cred.get_key("password")
        client = cred.get_key("client") or "100"
        verify_ssl_raw = cred.get_key("verify_ssl")
        verify_ssl = True if verify_ssl_raw is None else str(verify_ssl_raw).lower() == "true"

        if not base_url or not username or not password:
            raise ValueError(
                f"SAP credential '{credential_ref}' is missing one of required keys: "
                "base_url, username, password"
            )

        return cls(
            base_url=base_url,
            username=username,
            password=password,
            client=client,
            verify_ssl=verify_ssl,
        )


# Credential specification for validation
SAP_CREDENTIAL_SPEC = {
    "type": "object",
    "required": ["base_url", "username", "password"],
    "properties": {
        "base_url": {
            "type": "string",
            "description": "SAP S/4HANA OData base URL"
        },
        "username": {
            "type": "string",
            "description": "SAP username"
        },
        "password": {
            "type": "string",
            "description": "SAP password",
            "sensitive": True
        },
        "client": {
            "type": "string",
            "default": "100",
            "description": "SAP client number"
        },
        "verify_ssl": {
            "type": "boolean",
            "default": True,
            "description": "Verify SSL certificates"
        }
    }
}
