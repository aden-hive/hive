"""
Plaid Credential Management

Follows Hive's credentialSpec pattern for secure banking authentication.
"""

from dataclasses import dataclass
from typing import Optional

from framework.credentials.credential_spec import CredentialSpec
from framework.credentials.credential_store import CredentialStore


@dataclass
class PlaidCredentials:
    """Plaid API authentication credentials."""
    client_id: str
    secret: str
    environment: str = "sandbox"
    access_token: Optional[str] = None
    public_token: Optional[str] = None
    
    @classmethod
    def from_credential_store(cls, store: CredentialStore, credential_id: str) -> "PlaidCredentials":
        """Load credentials from Hive's credential store."""
        spec = store.get(credential_id)
        
        return cls(
            client_id=spec.get("client_id"),
            secret=spec.get("secret"),
            environment=spec.get("environment", "sandbox"),
            access_token=spec.get("access_token"),
            public_token=spec.get("public_token")
        )
    
    def to_credential_spec(self) -> CredentialSpec:
        """Convert to Hive credential spec format."""
        return CredentialSpec(
            credential_type="plaid",
            config={
                "client_id": self.client_id,
                "secret": self.secret,
                "environment": self.environment,
                "access_token": self.access_token,
                "public_token": self.public_token
            }
        )


# Credential specification for validation
PLAID_CREDENTIAL_SPEC = {
    "type": "object",
    "required": ["client_id", "secret"],
    "properties": {
        "client_id": {
            "type": "string",
            "description": "Plaid client ID"
        },
        "secret": {
            "type": "string",
            "description": "Plaid secret key",
            "sensitive": True
        },
        "environment": {
            "type": "string",
            "enum": ["sandbox", "development", "production"],
            "default": "sandbox",
            "description": "Plaid environment"
        },
        "access_token": {
            "type": "string",
            "description": "Plaid access token (obtained after account linking)",
            "sensitive": True
        },
        "public_token": {
            "type": "string",
            "description": "Temporary public token for account linking",
            "sensitive": True
        }
    }
}