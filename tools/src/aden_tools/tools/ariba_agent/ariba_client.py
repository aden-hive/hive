from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from .auth import OAuth2Client


class AribaClient:
    """
    Async client for SAP Ariba Discovery API.
    """

    BASE_URL = "https://api.ariba.com/v2/opportunities"

    def __init__(self) -> None:
        client_id = os.getenv("ARIBA_CLIENT_ID", "")
        client_secret = os.getenv("ARIBA_CLIENT_SECRET", "")

        self.auth = OAuth2Client(
            client_id=client_id,
            client_secret=client_secret,
            token_url="https://api.ariba.com/oauth/token",
        )

    async def search_async(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Perform opportunity search.

        Args:
            query: Structured query payload.

        Returns:
            List of opportunities.
        """
        token = await self.auth.get_token_async()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.BASE_URL,
                json=query,
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()

        data = response.json()
        return data.get("opportunities", [])
