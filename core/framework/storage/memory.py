"""
Semantic Memory Abstraction for Hive Core.

Provides a unified interface for long-term, persistent memory (Experience Layer).
"""

from typing import Any, Protocol, runtime_checkable
import logging
import httpx

logger = logging.getLogger(__name__)

@runtime_checkable
class MemoryProvider(Protocol):
    """Protocol for persistent memory providers."""
    
    async def add(self, content: str, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Store a new memory."""
        ...

    async def recall(self, query: str, user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant memories."""
        ...

class MemoriProvider:
    """Implementation of MemoryProvider using Memori.ai."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.memorilabs.ai/v1"

    async def add(self, content: str, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Store a new memory in Memori.ai."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"content": content}
        if user_id:
            payload["user_id"] = user_id
        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(f"{self.base_url}/memories", headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Memori add failed: {e}")
                return {"status": "error", "message": str(e)}

    async def recall(self, query: str, user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        """Recall relevant memories from Memori.ai."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "limit": limit}
        if user_id:
            payload["user_id"] = user_id

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(f"{self.base_url}/memories/search", headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Memori recall failed: {e}")
                return []
