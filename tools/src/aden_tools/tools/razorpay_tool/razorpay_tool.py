"""
Razorpay Tool - Online payments and billing management via Razorpay API.

Supports:
- API key authentication (RAZORPAY_API_KEY + RAZORPAY_API_SECRET)

Use Cases:
- List and filter payments
- Fetch payment details
- Create payment links
- List and fetch invoices
- Create refunds

API Reference: https://razorpay.com/docs/api/
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class _RazorpayClient:
    """Internal client wrapping Razorpay API calls."""

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret

    @property
    def _auth(self) -> tuple[str, str]:
        """HTTP Basic auth tuple."""
        return (self._api_key, self._api_secret)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid Razorpay API credentials"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Razorpay account access."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 400:
            try:
                detail = response.json().get("error", {}).get("description", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Bad request: {detail}"}
        if response.status_code == 429:
            return {"error": "Razorpay rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                error_data = response.json().get("error", {})
                detail = error_data.get("description", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Razorpay API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def list_payments(
        self,
        count: int = 10,
        skip: int = 0,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """List payments with optional filters."""
        params: dict[str, Any] = {
            "count": min(count, 100),
            "skip": skip,
        }
        if from_timestamp is not None:
            params["from"] = from_timestamp
        if to_timestamp is not None:
            params["to"] = to_timestamp

        response = httpx.get(
            f"{RAZORPAY_API_BASE}/payments",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            items = result.get("items", [])
            return {
                "count": result.get("count", len(items)),
                "payments": [
                    {
                        "id": p.get("id"),
                        "amount": p.get("amount"),
                        "currency": p.get("currency"),
                        "status": p.get("status"),
                        "method": p.get("method"),
                        "email": p.get("email"),
                        "contact": p.get("contact"),
                        "created_at": p.get("created_at"),
                        "description": p.get("description"),
                        "order_id": p.get("order_id"),
                    }
                    for p in items
                ],
            }
        return result

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch a single payment by ID."""
        response = httpx.get(
            f"{RAZORPAY_API_BASE}/payments/{payment_id}",
            auth=self._auth,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "id": result.get("id"),
                "amount": result.get("amount"),
                "currency": result.get("currency"),
                "status": result.get("status"),
                "method": result.get("method"),
                "email": result.get("email"),
                "contact": result.get("contact"),
                "created_at": result.get("created_at"),
                "description": result.get("description"),
                "order_id": result.get("order_id"),
                "error_code": result.get("error_code"),
                "error_description": result.get("error_description"),
                "captured": result.get("captured"),
                "fee": result.get("fee"),
                "tax": result.get("tax"),
                "refund_status": result.get("refund_status"),
                "amount_refunded": result.get("amount_refunded"),
            }
        return result

    def create_payment_link(
        self,
        amount: int,
        currency: str,
        description: str,
        customer_name: str | None = None,
        customer_email: str | None = None,
        customer_contact: str | None = None,
    ) -> dict[str, Any]:
        """Create a payment link."""
        body: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "description": description,
        }

        if customer_name or customer_email or customer_contact:
            body["customer"] = {}
            if customer_name:
                body["customer"]["name"] = customer_name
            if customer_email:
                body["customer"]["email"] = customer_email
            if customer_contact:
                body["customer"]["contact"] = customer_contact

        response = httpx.post(
            f"{RAZORPAY_API_BASE}/payment_links",
            auth=self._auth,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "id": result.get("id"),
                "short_url": result.get("short_url"),
                "amount": result.get("amount"),
                "currency": result.get("currency"),
                "description": result.get("description"),
                "status": result.get("status"),
                "created_at": result.get("created_at"),
                "customer": result.get("customer"),
            }
        return result

    def list_invoices(
        self,
        count: int = 10,
        skip: int = 0,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        """List invoices with optional filters."""
        params: dict[str, Any] = {
            "count": min(count, 100),
            "skip": skip,
        }
        if type_filter:
            params["type"] = type_filter

        response = httpx.get(
            f"{RAZORPAY_API_BASE}/invoices",
            auth=self._auth,
            params=params,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            items = result.get("items", [])
            return {
                "count": result.get("count", len(items)),
                "invoices": [
                    {
                        "id": inv.get("id"),
                        "amount": inv.get("amount"),
                        "currency": inv.get("currency"),
                        "status": inv.get("status"),
                        "customer_id": inv.get("customer_id"),
                        "created_at": inv.get("created_at"),
                        "description": inv.get("description"),
                        "short_url": inv.get("short_url"),
                    }
                    for inv in items
                ],
            }
        return result

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Fetch invoice details by ID."""
        response = httpx.get(
            f"{RAZORPAY_API_BASE}/invoices/{invoice_id}",
            auth=self._auth,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "id": result.get("id"),
                "amount": result.get("amount"),
                "currency": result.get("currency"),
                "status": result.get("status"),
                "customer_id": result.get("customer_id"),
                "customer_details": result.get("customer_details"),
                "line_items": result.get("line_items", []),
                "created_at": result.get("created_at"),
                "description": result.get("description"),
                "short_url": result.get("short_url"),
                "paid_at": result.get("paid_at"),
                "cancelled_at": result.get("cancelled_at"),
            }
        return result

    def create_refund(
        self,
        payment_id: str,
        amount: int | None = None,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a full or partial refund."""
        body: dict[str, Any] = {}
        if amount is not None:
            body["amount"] = amount
        if notes:
            body["notes"] = notes

        response = httpx.post(
            f"{RAZORPAY_API_BASE}/payments/{payment_id}/refund",
            auth=self._auth,
            json=body,
            timeout=30.0,
        )
        result = self._handle_response(response)

        if "error" not in result:
            return {
                "id": result.get("id"),
                "payment_id": result.get("payment_id"),
                "amount": result.get("amount"),
                "currency": result.get("currency"),
                "status": result.get("status"),
                "created_at": result.get("created_at"),
                "notes": result.get("notes"),
                "speed_processed": result.get("speed_processed"),
            }
        return result


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Razorpay payment tools with the MCP server."""

    def _get_credentials() -> tuple[str, str] | dict[str, str]:
        """Get Razorpay credentials from credential manager or environment."""
        if credentials is not None:
            api_key = credentials.get("razorpay")
            api_secret = credentials.get("razorpay_secret")

            if api_key is not None and not isinstance(api_key, str):
                api_key = None
            if api_secret is not None and not isinstance(api_secret, str):
                api_secret = None

            if api_key and api_secret:
                return api_key, api_secret
        else:
            api_key = os.getenv("RAZORPAY_API_KEY")
            api_secret = os.getenv("RAZORPAY_API_SECRET")

            if api_key and api_secret:
                return api_key, api_secret

        return {
            "error": "Razorpay credentials not configured",
            "help": (
                "Set RAZORPAY_API_KEY and RAZORPAY_API_SECRET environment variables. "
                "Get your credentials at https://dashboard.razorpay.com/app/keys"
            ),
        }

    def _get_client() -> _RazorpayClient | dict[str, str]:
        """Get a Razorpay client, or return an error dict if no credentials."""
        creds = _get_credentials()
        if isinstance(creds, dict):
            return creds
        return _RazorpayClient(creds[0], creds[1])

    # --- Payment Tools ---

    @mcp.tool()
    def razorpay_list_payments(
        count: int = 10,
        skip: int = 0,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
    ) -> dict:
        """
        List recent payments with optional filters.

        Args:
            count: Number of payments to fetch (1-100, default 10)
            skip: Number of payments to skip for pagination (default 0)
            from_timestamp: Unix timestamp to filter payments from
            to_timestamp: Unix timestamp to filter payments to

        Returns:
            Dict with payment list or error

        Example:
            razorpay_list_payments(count=20, from_timestamp=1640995200)
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if count < 1 or count > 100:
            count = max(1, min(100, count))

        try:
            return client.list_payments(count, skip, from_timestamp, to_timestamp)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def razorpay_get_payment(payment_id: str) -> dict:
        """
        Fetch a single payment by ID.

        Args:
            payment_id: Razorpay payment ID (e.g., "pay_AbcDefGhijkLmn")

        Returns:
            Dict with payment details or error

        Example:
            razorpay_get_payment("pay_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not payment_id or not re.match(r"^pay_[A-Za-z0-9]+$", payment_id):
            return {"error": "Invalid payment_id. Must match pattern: pay_[A-Za-z0-9]+"}

        try:
            return client.get_payment(payment_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def razorpay_create_payment_link(
        amount: int,
        currency: str,
        description: str,
        customer_name: str | None = None,
        customer_email: str | None = None,
        customer_contact: str | None = None,
    ) -> dict:
        """
        Create a one-time payment link.

        Args:
            amount: Amount in smallest currency unit (e.g., paise for INR)
            currency: Currency code (e.g., "INR", "USD")
            description: Description of the payment
            customer_name: Optional customer name
            customer_email: Optional customer email
            customer_contact: Optional customer phone number

        Returns:
            Dict with payment link details or error

        Example:
            razorpay_create_payment_link(
                amount=50000,
                currency="INR",
                description="Payment for invoice #123",
                customer_email="customer@example.com"
            )
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if amount <= 0:
            return {"error": "Amount must be positive"}
        if not currency or len(currency) != 3:
            return {"error": "Currency must be a 3-letter code (e.g., INR, USD)"}
        if not description:
            return {"error": "Description is required"}

        try:
            return client.create_payment_link(
                amount, currency, description, customer_name, customer_email, customer_contact
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def razorpay_list_invoices(
        count: int = 10,
        skip: int = 0,
        type_filter: str | None = None,
    ) -> dict:
        """
        List invoices with optional filters.

        Args:
            count: Number of invoices to fetch (1-100, default 10)
            skip: Number of invoices to skip for pagination (default 0)
            type_filter: Optional type filter (e.g., "invoice", "link")

        Returns:
            Dict with invoice list or error

        Example:
            razorpay_list_invoices(count=20, type_filter="invoice")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if count < 1 or count > 100:
            count = max(1, min(100, count))

        try:
            return client.list_invoices(count, skip, type_filter)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def razorpay_get_invoice(invoice_id: str) -> dict:
        """
        Fetch invoice details and line items.

        Args:
            invoice_id: Razorpay invoice ID (e.g., "inv_AbcDefGhijkLmn")

        Returns:
            Dict with invoice details or error

        Example:
            razorpay_get_invoice("inv_AbcDefGhijkLmn")
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not invoice_id or not re.match(r"^inv_[A-Za-z0-9]+$", invoice_id):
            return {"error": "Invalid invoice_id. Must match pattern: inv_[A-Za-z0-9]+"}

        try:
            return client.get_invoice(invoice_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def razorpay_create_refund(
        payment_id: str,
        amount: int | None = None,
        notes: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a full or partial refund for a payment.

        Args:
            payment_id: Razorpay payment ID (e.g., "pay_AbcDefGhijkLmn")
            amount: Optional refund amount in smallest currency unit (omit for full refund)
            notes: Optional dictionary of notes/metadata

        Returns:
            Dict with refund details or error

        Example:
            razorpay_create_refund("pay_AbcDefGhijkLmn", amount=10000)
            razorpay_create_refund("pay_AbcDefGhijkLmn", notes={"reason": "Customer request"})
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if not payment_id or not re.match(r"^pay_[A-Za-z0-9]+$", payment_id):
            return {"error": "Invalid payment_id. Must match pattern: pay_[A-Za-z0-9]+"}
        if amount is not None and amount <= 0:
            return {"error": "Refund amount must be positive"}

        try:
            return client.create_refund(payment_id, amount, notes)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
