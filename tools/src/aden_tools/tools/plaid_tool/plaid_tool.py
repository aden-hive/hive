"""
Plaid Tool - Banking & financial data aggregation via Plaid API.

Supports:
- Plaid client_id + secret authentication
- Account balances, transactions, institution lookup
- Sandbox, development, and production environments

API Reference: https://plaid.com/docs/api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_ENV = "sandbox"
BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _get_credentials(credentials: CredentialStoreAdapter | None) -> tuple[str | None, str | None]:
    """Return (client_id, secret)."""
    if credentials is not None:
        client_id = credentials.get("plaid_client_id")
        secret = credentials.get("plaid_secret")
        return client_id, secret
    return os.getenv("PLAID_CLIENT_ID"), os.getenv("PLAID_SECRET")


def _get_env() -> str:
    return os.getenv("PLAID_ENV", DEFAULT_ENV)


def _post(
    path: str, client_id: str, secret: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make a POST request to the Plaid API."""
    env = _get_env()
    base = BASE_URLS.get(env, BASE_URLS["sandbox"])
    payload = {**(body or {}), "client_id": client_id, "secret": secret}
    try:
        resp = httpx.post(
            f"{base}{path}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        data = resp.json()
        if resp.status_code != 200:
            err = data.get("error_message", data.get("error_code", f"HTTP {resp.status_code}"))
            return {"error": f"Plaid API error: {err}"}
        return data
    except httpx.TimeoutException:
        return {"error": "Request to Plaid timed out"}
    except Exception as e:
        return {"error": f"Plaid request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "PLAID_CLIENT_ID and PLAID_SECRET not set",
        "help": "Get credentials at https://dashboard.plaid.com/developers/keys",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Plaid tools with the MCP server."""

    @mcp.tool()
    def plaid_get_accounts(access_token: str) -> dict[str, Any]:
        """
        Get all accounts linked to a Plaid Item.

        Args:
            access_token: Plaid access token for the linked Item

        Returns:
            Dict with accounts list (account_id, name, type, subtype, balances)
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not access_token:
            return {"error": "access_token is required"}

        data = _post("/accounts/get", client_id, secret, {"access_token": access_token})
        if "error" in data:
            return data

        accounts = []
        for a in data.get("accounts", []):
            bal = a.get("balances") or {}
            accounts.append(
                {
                    "account_id": a.get("account_id", ""),
                    "name": a.get("name", ""),
                    "official_name": a.get("official_name", ""),
                    "type": a.get("type", ""),
                    "subtype": a.get("subtype", ""),
                    "mask": a.get("mask", ""),
                    "available_balance": bal.get("available"),
                    "current_balance": bal.get("current"),
                    "currency": bal.get("iso_currency_code", ""),
                }
            )
        return {"accounts": accounts, "count": len(accounts)}

    @mcp.tool()
    def plaid_get_balance(access_token: str) -> dict[str, Any]:
        """
        Get real-time balance for all accounts linked to a Plaid Item.

        Args:
            access_token: Plaid access token for the linked Item

        Returns:
            Dict with accounts and their real-time balances
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not access_token:
            return {"error": "access_token is required"}

        data = _post("/accounts/balance/get", client_id, secret, {"access_token": access_token})
        if "error" in data:
            return data

        accounts = []
        for a in data.get("accounts", []):
            bal = a.get("balances") or {}
            accounts.append(
                {
                    "account_id": a.get("account_id", ""),
                    "name": a.get("name", ""),
                    "type": a.get("type", ""),
                    "available": bal.get("available"),
                    "current": bal.get("current"),
                    "limit": bal.get("limit"),
                    "currency": bal.get("iso_currency_code", ""),
                }
            )
        return {"accounts": accounts}

    @mcp.tool()
    def plaid_sync_transactions(
        access_token: str,
        cursor: str = "",
        count: int = 100,
    ) -> dict[str, Any]:
        """
        Get incremental transaction updates using cursor-based sync.

        Args:
            access_token: Plaid access token for the linked Item
            cursor: Cursor from previous sync call (omit for full history)
            count: Number of transactions per page (1-500, default 100)

        Returns:
            Dict with added/modified/removed transactions and next_cursor
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not access_token:
            return {"error": "access_token is required"}

        body: dict[str, Any] = {
            "access_token": access_token,
            "count": max(1, min(count, 500)),
        }
        if cursor:
            body["cursor"] = cursor

        data = _post("/transactions/sync", client_id, secret, body)
        if "error" in data:
            return data

        def _fmt_txn(t: dict) -> dict:
            return {
                "transaction_id": t.get("transaction_id", ""),
                "account_id": t.get("account_id", ""),
                "amount": t.get("amount", 0),
                "date": t.get("date", ""),
                "name": t.get("name", ""),
                "merchant_name": t.get("merchant_name", ""),
                "category": t.get("category", []),
                "pending": t.get("pending", False),
                "currency": t.get("iso_currency_code", ""),
            }

        added = [_fmt_txn(t) for t in data.get("added", [])]
        modified = [_fmt_txn(t) for t in data.get("modified", [])]
        removed = [r.get("transaction_id", "") for r in data.get("removed", [])]

        return {
            "added": added,
            "modified": modified,
            "removed": removed,
            "next_cursor": data.get("next_cursor", ""),
            "has_more": data.get("has_more", False),
        }

    @mcp.tool()
    def plaid_get_transactions(
        access_token: str,
        start_date: str,
        end_date: str,
        count: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get transactions for a date range (non-incremental).

        Args:
            access_token: Plaid access token for the linked Item
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            count: Number of transactions per page (1-500, default 100)
            offset: Pagination offset (default 0)

        Returns:
            Dict with transactions list and total count
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not access_token or not start_date or not end_date:
            return {"error": "access_token, start_date, and end_date are required"}

        body: dict[str, Any] = {
            "access_token": access_token,
            "start_date": start_date,
            "end_date": end_date,
            "options": {
                "count": max(1, min(count, 500)),
                "offset": max(0, offset),
            },
        }
        data = _post("/transactions/get", client_id, secret, body)
        if "error" in data:
            return data

        txns = []
        for t in data.get("transactions", []):
            txns.append(
                {
                    "transaction_id": t.get("transaction_id", ""),
                    "account_id": t.get("account_id", ""),
                    "amount": t.get("amount", 0),
                    "date": t.get("date", ""),
                    "name": t.get("name", ""),
                    "merchant_name": t.get("merchant_name", ""),
                    "category": t.get("category", []),
                    "pending": t.get("pending", False),
                    "currency": t.get("iso_currency_code", ""),
                }
            )

        return {
            "transactions": txns,
            "total_transactions": data.get("total_transactions", 0),
        }

    @mcp.tool()
    def plaid_get_institution(
        institution_id: str,
        country_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get details about a financial institution by ID.

        Args:
            institution_id: Plaid institution ID (e.g. "ins_1")
            country_codes: ISO-3166-1 alpha-2 country codes (default ["US"])

        Returns:
            Dict with institution name, products, URL, and metadata
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not institution_id:
            return {"error": "institution_id is required"}

        body: dict[str, Any] = {
            "institution_id": institution_id,
            "country_codes": country_codes or ["US"],
            "options": {"include_optional_metadata": True},
        }
        data = _post("/institutions/get_by_id", client_id, secret, body)
        if "error" in data:
            return data

        inst = data.get("institution") or {}
        return {
            "institution_id": inst.get("institution_id", ""),
            "name": inst.get("name", ""),
            "products": inst.get("products", []),
            "country_codes": inst.get("country_codes", []),
            "url": inst.get("url", ""),
            "logo": inst.get("logo", ""),
            "oauth": inst.get("oauth", False),
        }

    @mcp.tool()
    def plaid_search_institutions(
        query: str,
        country_codes: list[str] | None = None,
        products: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Search for financial institutions by name.

        Args:
            query: Search query (institution name)
            country_codes: ISO-3166-1 alpha-2 country codes (default ["US"])
            products: Filter by supported products (e.g. ["transactions", "auth"])
            limit: Max results (1-50, default 10)

        Returns:
            Dict with matching institutions
        """
        client_id, secret = _get_credentials(credentials)
        if not client_id or not secret:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        body: dict[str, Any] = {
            "query": query,
            "country_codes": country_codes or ["US"],
            "options": {"include_optional_metadata": True, "limit": max(1, min(limit, 50))},
        }
        if products:
            body["products"] = products

        data = _post("/institutions/search", client_id, secret, body)
        if "error" in data:
            return data

        institutions = []
        for inst in data.get("institutions", []):
            institutions.append(
                {
                    "institution_id": inst.get("institution_id", ""),
                    "name": inst.get("name", ""),
                    "products": inst.get("products", []),
                    "country_codes": inst.get("country_codes", []),
                    "url": inst.get("url", ""),
                    "oauth": inst.get("oauth", False),
                }
            )
        return {"institutions": institutions, "count": len(institutions)}
