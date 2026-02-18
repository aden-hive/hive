"""
Base OAuth2 provider implementation.

This module provides a generic OAuth2 provider that works with standard
OAuth2 servers. OSS users can extend this class for custom providers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from ..models import CredentialObject, CredentialRefreshError, CredentialType
from ..provider import CredentialProvider
from .provider import (
    OAuth2Config,
    OAuth2Error,
    OAuth2Token,
    TokenPlacement,
)

logger = logging.getLogger(__name__)


class BaseOAuth2Provider(CredentialProvider):
    """
    Generic OAuth2 provider implementation.

    Works with standard OAuth2 servers (RFC 6749). Override methods for
    provider-specific behavior.

    Supported grant types:
    - Client Credentials: For server-to-server authentication
    - Refresh Token: For refreshing expired access tokens
    - Authorization Code: For user-authorized access (requires callback handling)

    OSS users can extend this class for custom providers:

        class GitHubOAuth2Provider(BaseOAuth2Provider):
            def __init__(self, client_id: str, client_secret: str):
                super().__init__(OAuth2Config(
                    token_url="https://github.com/login/oauth/access_token",
                    authorization_url="https://github.com/login/oauth/authorize",
                    client_id=client_id,
                    client_secret=client_secret,
                    default_scopes=["repo", "user"],
                ))

            def exchange_code(self, code: str, redirect_uri: str, **kwargs) -> OAuth2Token:
                # GitHub returns data as form-encoded by default
                # Override to handle this
                ...

    Example usage:
        provider = BaseOAuth2Provider(OAuth2Config(
            token_url="https://oauth2.example.com/token",
            client_id="my-client-id",
            client_secret="my-client-secret",
        ))

        # Get token using client credentials
        token = provider.client_credentials_grant()

        # Refresh an expired token
        new_token = provider.refresh_token(old_token.refresh_token)
    """

    def __init__(self, config: OAuth2Config, provider_id: str = "oauth2"):
        """
        Initialize the OAuth2 provider.

        Args:
            config: OAuth2 configuration
            provider_id: Unique identifier for this provider instance
        """
        self.config = config
        self._provider_id = provider_id
        self._client: Any | None = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.OAUTH2, CredentialType.BEARER_TOKEN]

    def _get_client(self) -> Any:
        """Get or create HTTP client."""
        if self._client is None:
            try:
                import httpx

                self._client = httpx.Client(timeout=self.config.request_timeout)
            except ImportError as e:
                raise ImportError(
                    "OAuth2 provider requires 'httpx'. Install with: uv pip install httpx"
                ) from e
        return self._client

    def _close_client(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self) -> None:
        """Cleanup HTTP client on deletion."""
        self._close_client()

    # --- Grant Types ---

    def get_authorization_url(
        self,
        state: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Generate authorization URL for user consent (Authorization Code flow).

        Args:
            state: Anti-CSRF state parameter (should be random and verified)
            redirect_uri: Callback URL to receive the authorization code
            scopes: Requested scopes (defaults to config.default_scopes)
            **kwargs: Additional provider-specific parameters

        Returns:
            URL to redirect user for authorization

        Raises:
            ValueError: If authorization_url is not configured
        """
        if not self.config.authorization_url:
            raise ValueError("authorization_url not configured for this provider")

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": " ".join(scopes or self.config.default_scopes),
            **kwargs,
        }

        return f"{self.config.authorization_url}?{urlencode(params)}"

    def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        **kwargs: Any,
    ) -> OAuth2Token:
        """
        Exchange authorization code for tokens (Authorization Code flow).

        Args:
            code: Authorization code from callback
            redirect_uri: Same redirect_uri used in authorization request
            **kwargs: Additional provider-specific parameters

        Returns:
            OAuth2Token with access_token and optional refresh_token

        Raises:
            OAuth2Error: If token exchange fails
        """
        data = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            **self.config.extra_token_params,
            **kwargs,
        }

        return self._token_request(data)

    def client_credentials_grant(
        self,
        scopes: list[str] | None = None,
        **kwargs: Any,
    ) -> OAuth2Token:
        """
        Obtain token using client credentials (Client Credentials flow).

        This is for server-to-server authentication where no user is involved.

        Args:
            scopes: Requested scopes (defaults to config.default_scopes)
            **kwargs: Additional provider-specific parameters

        Returns:
            OAuth2Token (typically without refresh_token)

        Raises:
            OAuth2Error: If token request fails
        """
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            **self.config.extra_token_params,
            **kwargs,
        }

        if scopes or self.config.default_scopes:
            data["scope"] = " ".join(scopes or self.config.default_scopes)

        return self._token_request(data)

    def refresh_access_token(
        self,
        refresh_token: str,
        scopes: list[str] | None = None,
        **kwargs: Any,
    ) -> OAuth2Token:
        """
        Refresh an expired access token (Refresh Token flow).

        Args:
            refresh_token: The refresh token
            scopes: Scopes to request (defaults to original scopes)
            **kwargs: Additional provider-specific parameters

        Returns:
            New OAuth2Token (may include new refresh_token)

        Raises:
            OAuth2Error: If refresh fails
            RefreshTokenInvalidError: If refresh token is revoked/invalid
        """
        data = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
            **self.config.extra_token_params,
            **kwargs,
        }

        if scopes:
            data["scope"] = " ".join(scopes)

        return self._token_request(data)

    def revoke_token(
        self,
        token: str,
        token_type_hint: str = "access_token",
    ) -> bool:
        """
        Revoke a token (RFC 7009).

        Args:
            token: The token to revoke
            token_type_hint: "access_token" or "refresh_token"

        Returns:
            True if revocation succeeded
        """
        if not self.config.revocation_url:
            logger.warning("revocation_url not configured, cannot revoke token")
            return False

        try:
            client = self._get_client()
            response = client.post(
                self.config.revocation_url,
                data={
                    "token": token,
                    "token_type_hint": token_type_hint,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
                headers={"Accept": "application/json", **self.config.extra_headers},
            )
            # RFC 7009: 200 indicates success (even if token was already invalid)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Token revocation failed: {e}")
            return False

    # --- CredentialProvider Interface ---

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """
        Refresh a credential using its refresh token.

        Implements CredentialProvider.refresh().

        Args:
            credential: The credential to refresh

        Returns:
            Updated credential with new access_token

        Raises:
            CredentialRefreshError: If refresh fails
        """
        refresh_tok = credential.get_key("refresh_token")
        if not refresh_tok:
            raise CredentialRefreshError(f"Credential '{credential.id}' has no refresh_token")

        try:
            new_token = self.refresh_access_token(refresh_tok)
        except OAuth2Error as e:
            if e.error == "invalid_grant":
                raise CredentialRefreshError(
                    f"Refresh token for '{credential.id}' is invalid or revoked. "
                    "Re-authorization required."
                ) from e
            raise CredentialRefreshError(f"Failed to refresh '{credential.id}': {e}") from e

        # Update credential
        credential.set_key("access_token", new_token.access_token, expires_at=new_token.expires_at)

        # Update refresh token if a new one was issued
        if new_token.refresh_token and new_token.refresh_token != refresh_tok:
            credential.set_key("refresh_token", new_token.refresh_token)

        credential.last_refreshed = datetime.now(UTC)
        logger.info(f"Refreshed OAuth2 credential '{credential.id}'")

        return credential

    def validate(self, credential: CredentialObject) -> bool:
        """
        Validate that credential has a valid (non-expired) access_token.

        Args:
            credential: The credential to validate

        Returns:
            True if credential has valid access_token
        """
        access_key = credential.keys.get("access_token")
        if access_key is None:
            return False
        return not access_key.is_expired

    def should_refresh(self, credential: CredentialObject) -> bool:
        """
        Check if credential should be refreshed.

        Returns True if access_token is expired or within 5 minutes of expiry.
        """
        access_key = credential.keys.get("access_token")
        if access_key is None:
            return False

        if access_key.expires_at is None:
            return False

        buffer = timedelta(minutes=5)
        return datetime.now(UTC) >= (access_key.expires_at - buffer)

    def revoke(self, credential: CredentialObject) -> bool:
        """
        Revoke all tokens in a credential.

        Args:
            credential: The credential to revoke

        Returns:
            True if all revocations succeeded
        """
        success = True

        # Revoke access token
        access_token = credential.get_key("access_token")
        if access_token:
            if not self.revoke_token(access_token, "access_token"):
                success = False

        # Revoke refresh token
        refresh_token = credential.get_key("refresh_token")
        if refresh_token:
            if not self.revoke_token(refresh_token, "refresh_token"):
                success = False

        return success

    # --- Token Request Helpers ---

    def _token_request(self, data: dict[str, Any]) -> OAuth2Token:
        """
        Make a token request to the OAuth2 server.

        Args:
            data: Form data for the token request

        Returns:
            OAuth2Token from the response

        Raises:
            OAuth2Error: If request fails or returns an error
        """
        client = self._get_client()

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            **self.config.extra_headers,
        }

        response = client.post(self.config.token_url, data=data, headers=headers)

        # Parse response
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            response_data = response.json()
        else:
            # Some providers (like GitHub) may return form-encoded
            response_data = self._parse_form_response(response.text)

        # Check for error
        if response.status_code != 200 or "error" in response_data:
            error = response_data.get("error", "unknown_error")
            description = response_data.get("error_description", response.text)
            raise OAuth2Error(
                error=error, description=description, status_code=response.status_code
            )

        return OAuth2Token.from_token_response(response_data)

    def _parse_form_response(self, text: str) -> dict[str, str]:
        """Parse form-encoded response (some providers use this instead of JSON)."""
        from urllib.parse import parse_qs

        parsed = parse_qs(text)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    # --- Token Formatting for Requests ---

    def format_for_request(self, token: OAuth2Token) -> dict[str, Any]:
        """
        Format token for use in HTTP requests (bipartisan model).

        Args:
            token: The OAuth2 token

        Returns:
            Dict with 'headers', 'params', or 'data' keys as appropriate
        """
        placement = self.config.token_placement

        if placement == TokenPlacement.HEADER_BEARER:
            return {"headers": {"Authorization": f"{token.token_type} {token.access_token}"}}

        elif placement == TokenPlacement.HEADER_CUSTOM:
            header_name = self.config.custom_header_name or "X-Access-Token"
            return {"headers": {header_name: token.access_token}}

        elif placement == TokenPlacement.QUERY_PARAM:
            return {"params": {self.config.query_param_name: token.access_token}}

        elif placement == TokenPlacement.BODY_PARAM:
            return {"data": {"access_token": token.access_token}}

        return {}

    def format_credential_for_request(self, credential: CredentialObject) -> dict[str, Any]:
        """
        Format a credential for use in HTTP requests.

        Args:
            credential: The credential containing access_token

        Returns:
            Dict with 'headers', 'params', or 'data' keys as appropriate
        """
        access_token = credential.get_key("access_token")
        if not access_token:
            return {}

        token = OAuth2Token(
            access_token=access_token,
            token_type=credential.keys.get("token_type", "Bearer") or "Bearer",
        )

        return self.format_for_request(token)
