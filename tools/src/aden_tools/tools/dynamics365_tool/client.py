"""Main client for Microsoft Dynamics 365 Dataverse API."""

import time
from typing import Any

import httpx

from aden_tools.credentials import CredentialError


class Dynamics365Client:
    """Client for interacting with Microsoft Dynamics 365 Dataverse API."""

    def __init__(self, credential_string: str):
        """
        Initialize the client.

        Args:
            credential_string: String in format "tenant_id:client_id:client_secret:environment"
        """
        try:
            parts = credential_string.split(":", 3)
            if len(parts) != 4:
                raise ValueError("Format must be tenant_id:client_id:client_secret:environment")
            self.tenant_id = parts[0]
            self.client_id = parts[1]
            self.client_secret = parts[2]
            self.environment = parts[3].rstrip("/")
        except Exception as e:
            raise CredentialError(
                f"Invalid Dynamics 365 credential format: {e}. "
                "Expected 'tenant_id:client_id:client_secret:environment'"
            ) from e

        self.api_url = f"{self.environment}/api/data/v9.2"
        self._token: str | None = None
        self._token_expires_at: float = 0

    async def _get_token(self) -> str:
        """Retrieve an OAuth2 token using client credentials flow."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": f"{self.environment}/.default",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            if response.status_code != 200:
                raise Exception(f"Failed to retrieve token: {response.text}")
            
            res_json = response.json()
            self._token = res_json["access_token"]
            # Set expiration with a safety buffer
            expires_in = res_json.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in
            return self._token

    async def request(
        self, method: str, path: str, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None
    ) -> Any:
        """
        Make an authorized request to the Dataverse API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            path: API path (e.g., "accounts")
            params: Query parameters
            json: JSON body for POST/PATCH

        Returns:
            The parsed JSON response or None for 204 No Content
        """
        token = await self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Prefer": "return=representation",  # Get created/updated object back
        }

        url = f"{self.api_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json)
            
            if response.status_code == 204:
                return None
                
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    message = error_data.get("error", {}).get("message", response.text)
                except Exception:
                    message = response.text
                raise Exception(f"Dynamics 365 API error ({response.status_code}): {message}")
                
            return response.json()
