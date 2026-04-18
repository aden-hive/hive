from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx


class OAuth2Client:
    """
    Async OAuth2 client with concurrency-safe token refresh.
    """

    def __init__(self, client_id: str, client_secret: str, token_url: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url

        self._token: Optional[str] = None
        self._expiry: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token_async(self) -> str:
        """
        Retrieve a valid OAuth2 token, refreshing if expired.

        Returns:
            str: Access token.
        """
        if self._token and time.monotonic() < self._expiry:
            return self._token

        async with self._lock:
            if self._token and time.monotonic() < self._expiry:
                return self._token

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=10,
                )
                response.raise_for_status()

            data = response.json()
            self._token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 3600))

            self._expiry = time.monotonic() + max(0, expires_in - 60)
            return self._token
