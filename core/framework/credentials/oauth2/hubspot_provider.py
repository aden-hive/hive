"""
HubSpot-specific OAuth2 provider.

Pre-configured for HubSpot's OAuth2 endpoints and CRM scopes.
Extends BaseOAuth2Provider for HubSpot-specific behavior.

Usage:
    provider = HubSpotOAuth2Provider(
        client_id="your-client-id",
        client_secret="your-client-secret",
    )

    # Use with credential store
    store = CredentialStore(
        storage=EncryptedFileStorage(),  # defaults to ~/.hive/credentials
        providers=[provider],
    )

See: https://developers.hubspot.com/docs/api/oauth-quickstart-guide
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import CredentialObject, CredentialType
from .base_provider import BaseOAuth2Provider
from .provider import OAuth2Config

logger = logging.getLogger(__name__)

# HubSpot OAuth2 endpoints
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_AUTHORIZATION_URL = "https://app.hubspot.com/oauth/authorize"

# Default CRM scopes for contacts, companies, and deals
HUBSPOT_DEFAULT_SCOPES = [
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
]


class HubSpotOAuth2Provider(BaseOAuth2Provider):
    """
    HubSpot OAuth2 provider with pre-configured endpoints.

    Handles HubSpot-specific OAuth2 behavior:
    - Pre-configured token and authorization URLs
    - Default CRM scopes for contacts, companies, and deals
    - Token validation via HubSpot API

    Example:
        provider = HubSpotOAuth2Provider(
            client_id="your-hubspot-client-id",
            client_secret="your-hubspot-client-secret",
            scopes=["crm.objects.contacts.read"],  # Override default scopes
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None = None,
    ):
        config = OAuth2Config(
            token_url=HUBSPOT_TOKEN_URL,
            authorization_url=HUBSPOT_AUTHORIZATION_URL,
            client_id=client_id,
            client_secret=client_secret,
            default_scopes=scopes or HUBSPOT_DEFAULT_SCOPES,
        )
        super().__init__(config, provider_id="hubspot_oauth2")

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.OAUTH2]

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate HubSpot credential by making a lightweight API call.

        Tests the access token against the contacts endpoint with limit=1.
        """
        access_token = credential.get_key("access_token")
        if not access_token:
            return False

        try:
            client = self._get_client()
            response = client.get(
                "https://api.hubapi.com/crm/v3/objects/contacts",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                params={"limit": "1"},
            )
            return response.status_code == 200
        except Exception:
            return False

    def _parse_token_response(self, response_data: dict[str, Any]) -> Any:
        """Parse HubSpot token response."""
        from .provider import OAuth2Token

        return OAuth2Token.from_token_response(response_data)
