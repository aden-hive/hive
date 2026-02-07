"""
SAP S/4HANA Credential Management

Follows Hive's credentialSpec pattern for secure authentication.
"""

from dataclasses import dataclass
from typing import Optional

from framework.credentials.credential_spec import CredentialSpec
from framework.credentials.credential_store import CredentialStore


@dataclass
class SAPCredentials:
    """SAP S/4HANA authentication credentials."""
    base_url: str
    username: str
    password: str
    client: str = "100"
    verify_ssl: bool = True
    
    @classmethod
    def from_credential_store(cls, store: CredentialStore, credential_id: str) -> "SAPCredentials":
        """Load credentials from Hive's credential store."""
        spec = store.get(credential_id)
        
        return cls(
            base_url=spec.get("base_url"),
            username=spec.get("username"),
            password=spec.get("password"),
            client=spec.get("client", "100"),
            verify_ssl=spec.get("verify_ssl", True)
        )
    
    def to_credential_spec(self) -> CredentialSpec:
        """Convert to Hive credential spec format."""
        return CredentialSpec(
            credential_type="sap_s4hana",
            config={
                "base_url": self.base_url,
                "username": self.username,
                "password": self.password,
                "client": self.client,
                "verify_ssl": self.verify_ssl
            }
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