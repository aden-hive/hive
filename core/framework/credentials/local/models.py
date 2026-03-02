"""
Data models for the local credential registry.

LocalAccountInfo mirrors AdenIntegrationInfo, giving local API key credentials
the same identity/status metadata as Aden OAuth credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from framework.credentials.models import CredentialIdentity


@dataclass
class LocalAccountInfo:
    """
    A locally-stored named credential account.

    Mirrors AdenIntegrationInfo so local and Aden accounts can be treated
    uniformly in the credential tester and account selection UI.

    Attributes:
        credential_id: The logical credential name (e.g. "brave_search", "github")
        alias: User-provided name for this account (e.g. "work", "personal")
        status: "active" | "failed" | "unknown"
        identity: Email, username, workspace, or account_id extracted from health check
        last_validated: When the key was last verified against the live API
        created_at: When this account was first stored
    """

    credential_id: str
    alias: str
    status: str = "unknown"
    identity: CredentialIdentity = field(default_factory=CredentialIdentity)
    last_validated: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def storage_id(self) -> str:
        """The key used in EncryptedFileStorage: '{credential_id}/{alias}'."""
        return f"{self.credential_id}/{self.alias}"

    def to_account_dict(self) -> dict:
        """
        Format compatible with AccountSelectionScreen and configure_for_account().

        Same shape as Aden account dicts, with source='local' added.
        """
        return {
            "provider": self.credential_id,
            "alias": self.alias,
            "identity": self.identity.to_dict(),
            "integration_id": None,
            "source": "local",
            "status": self.status,
        }
