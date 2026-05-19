"""
Zoho CRM-specific OAuth2 provider.

Pre-configured for Zoho's OAuth2 endpoints and CRM scopes.
Extends BaseOAuth2Provider for Zoho-specific behavior.

Usage:
    provider = ZohoOAuth2Provider(
        client_id="your-client-id",
        client_secret="your-client-secret",
        accounts_domain="https://accounts.zoho.com",  # or .in, .eu, etc.
    )

    # Use with credential store
    store = CredentialStore(
        storage=EncryptedFileStorage(),
        providers=[provider],
    )

See: https://www.zoho.com/crm/developer/docs/api/v2/access-refresh.html
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..models import CredentialObject, CredentialRefreshError, CredentialType
from .base_provider import BaseOAuth2Provider
from .provider import OAuth2Config, OAuth2Token, TokenPlacement

logger = logging.getLogger(__name__)

# Default CRM scopes for Phase 1 (Leads, Contacts, Accounts, Deals, Notes)
ZOHO_DEFAULT_SCOPES = [
    "ZohoCRM.modules.leads.ALL",
    "ZohoCRM.modules.contacts.ALL",
    "ZohoCRM.modules.accounts.ALL",
    "ZohoCRM.modules.deals.ALL",
    "ZohoCRM.modules.notes.CREATE",
]


class ZohoOAuth2Provider(BaseOAuth2Provider):
    """
    Zoho CRM OAuth2 provider with pre-configured endpoints.

    Handles Zoho-specific OAuth2 behavior:
    - Pre-configured token and authorization URLs (region-aware)
    - Default CRM scopes for Leads, Contacts, Accounts, Deals, Notes
    - Token validation via Zoho CRM API
    - Authorization header format: "Authorization: Zoho-oauthtoken {token}"

    Example:
        provider = ZohoOAuth2Provider(
            client_id="your-zoho-client-id",
            client_secret="your-zoho-client-secret",
            accounts_domain="https://accounts.zoho.com",  # US
            # or "https://accounts.zoho.in" for India
            # or "https://accounts.zoho.eu" for EU
        )
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        accounts_domain: str = "https://accounts.zoho.com",
        api_domain: str | None = None,
        scopes: list[str] | None = None,
    ):
        """
        Initialize Zoho OAuth2 provider.

        Args:
            client_id: Zoho OAuth2 client ID
            client_secret: Zoho OAuth2 client secret
            accounts_domain: Zoho accounts domain (region-specific)
                - US: https://accounts.zoho.com
                - India: https://accounts.zoho.in
                - EU: https://accounts.zoho.eu
                - etc.
            api_domain: Zoho API domain for CRM calls (used in validate).
                Defaults to ZOHO_API_DOMAIN env or https://www.zohoapis.com
            scopes: Override default scopes if needed
        """
        base = accounts_domain.rstrip("/")
        token_url = f"{base}/oauth/v2/token"
        auth_url = f"{base}/oauth/v2/auth"

        config = OAuth2Config(
            token_url=token_url,
            authorization_url=auth_url,
            client_id=client_id,
            client_secret=client_secret,
            default_scopes=scopes or ZOHO_DEFAULT_SCOPES,
            token_placement=TokenPlacement.HEADER_CUSTOM,
            custom_header_name="Authorization",
        )
        super().__init__(config, provider_id="zoho_crm_oauth2")
        self._accounts_domain = base
        self._api_domain = (
            api_domain or os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.com")
        ).rstrip("/")

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.OAUTH2]

    def format_for_request(self, token: OAuth2Token) -> dict[str, Any]:
        """
        Format token for Zoho CRM API requests.

        Zoho uses Authorization header: "Zoho-oauthtoken {access_token}"
        (not Bearer).
        """
        return {
            "headers": {
                "Authorization": f"Zoho-oauthtoken {token.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        }

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate Zoho credential by making a lightweight API call.

        Uses GET /crm/v2/users?type=CurrentUser (doesn't require module access).
        Treats 429 as valid-but-rate-limited.
        """
        access_token = credential.get_key("access_token")
        if not access_token:
            return False

        try:
            client = self._get_client()
            response = client.get(
                f"{self._api_domain}/crm/v2/users?type=CurrentUser",
                headers={
                    "Authorization": f"Zoho-oauthtoken {access_token}",
                    "Accept": "application/json",
                },
                timeout=self.config.request_timeout,
            )
            return response.status_code in (200, 429)
        except Exception as e:
            logger.debug("Zoho credential validation failed: %s", e)
            return False

    def _parse_token_response(self, response_data: dict[str, Any]) -> OAuth2Token:
        """
        Parse Zoho token response.

        Zoho returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600,
            "api_domain": "https://www.zohoapis.com",
            "token_type": "Bearer"
        }
        """
        token = OAuth2Token.from_token_response(response_data)
        if "api_domain" in response_data:
            token.raw_response["api_domain"] = response_data["api_domain"]
        return token

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """Refresh Zoho OAuth2 credential and persist DC metadata."""
        refresh_tok = credential.get_key("refresh_token")
        if not refresh_tok:
            raise CredentialRefreshError(f"Credential '{credential.id}' has no refresh_token")

        try:
            new_token = self.refresh_access_token(refresh_tok)
        except Exception as e:
            raise CredentialRefreshError(f"Failed to refresh '{credential.id}': {e}") from e

        credential.set_key("access_token", new_token.access_token, expires_at=new_token.expires_at)

        if new_token.refresh_token and new_token.refresh_token != refresh_tok:
            credential.set_key("refresh_token", new_token.refresh_token)

        api_domain = new_token.raw_response.get("api_domain")
        if isinstance(api_domain, str) and api_domain:
            credential.set_key("api_domain", api_domain.rstrip("/"))

        accounts_server = new_token.raw_response.get("accounts-server")
        if isinstance(accounts_server, str) and accounts_server:
            credential.set_key("accounts_domain", accounts_server.rstrip("/"))

        location = new_token.raw_response.get("location")
        if isinstance(location, str) and location:
            credential.set_key("location", location.strip().lower())

        return credential
