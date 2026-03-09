"""
Scribeless Tool - Handwritten letter sending via Scribeless API.

Supports:
- API key authentication (SCRIBELESS_API_KEY)
- Handwritten letter creation and sending
- Multiple paper styles and handwriting options

Use Cases:
- Direct mail campaigns with personal touch
- Thank you notes
- Follow-up letters after meetings
- Account-Based Marketing direct mail

API Reference: https://scribeless.org/docs
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

SCRIBELESS_API_BASE = "https://api.scribeless.org/api/v1"


class _ScribelessClient:
    """Internal client wrapping Scribeless API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Scribeless API key"}
        if response.status_code == 402:
            return {"error": "Insufficient credits. Check your Scribeless balance."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 422:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Invalid parameters: {detail}"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Scribeless API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def send_letter(
        self,
        recipient_name: str,
        recipient_address: str,
        recipient_city: str,
        recipient_state: str,
        recipient_zip: str,
        recipient_country: str,
        message: str,
        style: str = "classic",
        paper_color: str = "white",
    ) -> dict[str, Any]:
        """Send a handwritten letter."""
        payload = {
            "recipient": {
                "name": recipient_name,
                "address_line_1": recipient_address,
                "city": recipient_city,
                "state": recipient_state,
                "postal_code": recipient_zip,
                "country": recipient_country,
            },
            "message": message,
            "style": style,
            "paper_color": paper_color,
        }

        response = httpx.post(
            f"{SCRIBELESS_API_BASE}/letters/send",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "success": True,
                "letter_id": result.get("id"),
                "status": result.get("status", "queued"),
                "estimated_delivery": result.get("estimated_delivery"),
                "cost": result.get("cost"),
            }
        return result

    def get_letter_status(self, letter_id: str) -> dict[str, Any]:
        """Get status of a sent letter."""
        response = httpx.get(
            f"{SCRIBELESS_API_BASE}/letters/{letter_id}",
            headers=self._headers,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "letter_id": letter_id,
                "status": result.get("status"),
                "tracking_number": result.get("tracking_number"),
                "sent_at": result.get("sent_at"),
                "delivered_at": result.get("delivered_at"),
            }
        return result

    def get_balance(self) -> dict[str, Any]:
        """Get account balance and credit info."""
        response = httpx.get(
            f"{SCRIBELESS_API_BASE}/account/balance",
            headers=self._headers,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "balance": result.get("balance"),
                "credits_remaining": result.get("credits_remaining"),
                "currency": result.get("currency", "USD"),
            }
        return result


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Scribeless tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Scribeless API key from credentials or environment."""
        if credentials is not None:
            return credentials.get("scribeless")
        return os.getenv("SCRIBELESS_API_KEY")

    def _get_client() -> _ScribelessClient | dict[str, str]:
        """Get a Scribeless client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Scribeless credentials not configured",
                "help": (
                    "Set SCRIBELESS_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get your API key at https://scribeless.org/dashboard/api"
                ),
            }
        return _ScribelessClient(api_key)

    @mcp.tool()
    def scribeless_send_letter(
        recipient_name: str,
        recipient_address: str,
        recipient_city: str,
        recipient_state: str,
        recipient_zip: str,
        recipient_country: str = "USA",
        message: str = "",
        style: str = "classic",
        paper_color: str = "white",
    ) -> dict:
        """
        Send a handwritten letter via Scribeless.

        Args:
            recipient_name: Recipient's full name
            recipient_address: Street address (line 1)
            recipient_city: City
            recipient_state: State or province
            recipient_zip: Postal/ZIP code
            recipient_country: Country code (default: "USA")
            message: Letter content (keep concise for handwritten format)
            style: Handwriting style - "classic", "modern", "elegant" (default: "classic")
            paper_color: Paper color - "white", "cream", "kraft" (default: "white")

        Returns:
            Dict with:
            - success: Boolean indicating if letter was queued
            - letter_id: Unique identifier for tracking
            - status: Current status (queued, printing, sent, delivered)
            - estimated_delivery: Expected delivery date
            - cost: Cost in credits or currency

        Example:
            scribeless_send_letter(
                recipient_name="John Doe",
                recipient_address="123 Main St",
                recipient_city="San Francisco",
                recipient_state="CA",
                recipient_zip="94102",
                message="Dear John,\\n\\nI wanted to personally reach out..."
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not message:
            return {"error": "Message content is required"}

        try:
            return client.send_letter(
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                recipient_city=recipient_city,
                recipient_state=recipient_state,
                recipient_zip=recipient_zip,
                recipient_country=recipient_country,
                message=message,
                style=style,
                paper_color=paper_color,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def scribeless_get_status(letter_id: str) -> dict:
        """
        Get the status of a sent letter.

        Args:
            letter_id: The letter ID returned from scribeless_send_letter

        Returns:
            Dict with:
            - letter_id: The letter identifier
            - status: Current status (queued, printing, sent, delivered, failed)
            - tracking_number: USPS tracking number if available
            - sent_at: Timestamp when letter was sent
            - delivered_at: Timestamp when letter was delivered (if applicable)

        Example:
            scribeless_get_status(letter_id="letter_abc123")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_letter_status(letter_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def scribeless_get_balance() -> dict:
        """
        Get your Scribeless account balance and remaining credits.

        Returns:
            Dict with:
            - balance: Account balance
            - credits_remaining: Number of letter credits available
            - currency: Currency code (USD, EUR, etc.)

        Example:
            scribeless_get_balance()
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        try:
            return client.get_balance()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
