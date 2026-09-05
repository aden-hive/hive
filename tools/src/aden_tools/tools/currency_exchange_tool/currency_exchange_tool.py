"""
Currency Exchange Tool - Real-time and historical FX rates.

Uses the Frankfurter API backed by the European Central Bank.
No API key or authentication required.

Reference: https://api.frankfurter.dev
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

import httpx
from fastmcp import FastMCP

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"
REQUEST_TIMEOUT = 10.0


def _normalize_currency_code(
    value: str, field_name: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize and validate a 3-letter ISO currency code."""
    normalized = value.strip().upper()
    if not normalized:
        return None, {"error": f"{field_name} is required"}
    if len(normalized) != 3 or not normalized.isalpha():
        return None, {"error": f"{field_name} must be a 3-letter currency code"}
    return normalized, None


def _extract_error_message(response: httpx.Response) -> str:
    """Extract a readable API error message from a Frankfurter response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "request failed"

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return "request failed"


def _request_json(
    endpoint: str, params: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Call the Frankfurter API and normalize transport and HTTP errors."""
    try:
        response = httpx.get(
            f"{FRANKFURTER_BASE}/{endpoint}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.TimeoutException:
        return None, {"error": "Frankfurter API request timed out"}
    except httpx.RequestError as exc:
        return None, {"error": f"Frankfurter API request failed: {exc!s}"}

    if response.status_code >= 400:
        message = _extract_error_message(response)
        if response.status_code == 429:
            return None, {"error": "Frankfurter API rate limited the request"}
        return None, {
            "status_code": response.status_code,
            "message": message,
            "error": f"Frankfurter API returned {response.status_code}: {message}",
        }

    try:
        payload = response.json()
    except ValueError:
        return None, {"error": "Frankfurter API returned invalid JSON"}

    if not isinstance(payload, dict):
        return None, {"error": "Frankfurter API returned an unexpected response shape"}

    return payload, None


def _parse_historical_date(value: str) -> tuple[str | None, dict[str, Any] | None]:
    """Validate a historical date before sending the API request."""
    normalized = value.strip()
    if not normalized:
        return None, {"error": "date is required (YYYY-MM-DD)"}

    try:
        date_type.fromisoformat(normalized)
    except ValueError:
        return None, {"error": "date must use YYYY-MM-DD format"}

    return normalized, None


def register_tools(mcp: FastMCP) -> None:
    """Register currency exchange tools with the MCP server."""

    @mcp.tool()
    def currency_get_latest(base: str = "USD") -> dict[str, Any]:
        """
        Get the latest exchange rates for a base currency.

        Args:
            base: Base currency code (e.g. "USD", "EUR", "GBP"). Default is "USD".

        Returns:
            Dict with base currency, date, and rates against all available currencies.
        """
        normalized_base, error = _normalize_currency_code(base, "base")
        if error:
            return error

        data, error = _request_json("latest", params={"base": normalized_base})
        if error:
            if error.get("status_code") == 404:
                return {"error": f"Unknown currency code: {normalized_base}"}
            return {"error": error["error"]}

        return {
            "base": data.get("base"),
            "date": data.get("date"),
            "rates": data.get("rates", {}),
            "count": len(data.get("rates", {})),
        }

    @mcp.tool()
    def currency_convert(
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> dict[str, Any]:
        """
        Convert an amount from one currency to another.

        Args:
            amount: Amount to convert (e.g. 100.0)
            from_currency: Source currency code (e.g. "USD")
            to_currency: Target currency code (e.g. "EUR")

        Returns:
            Dict with original amount, converted amount, rate, and date.
        """
        source_currency, error = _normalize_currency_code(from_currency, "from_currency")
        if error:
            return error

        target_currency, error = _normalize_currency_code(to_currency, "to_currency")
        if error:
            return error

        if amount < 0:
            return {"error": "amount must be greater than or equal to 0"}

        if source_currency == target_currency:
            return {
                "from": source_currency,
                "to": target_currency,
                "amount": amount,
                "converted": amount,
                "rate": 1.0,
                "date": None,
            }

        data, error = _request_json(
            "latest",
            params={
                "amount": amount,
                "base": source_currency,
                "symbols": target_currency,
            },
        )
        if error:
            if error.get("status_code") == 404:
                return {"error": (f"Unknown currency code: {source_currency} or {target_currency}")}
            return {"error": error["error"]}

        converted = data.get("rates", {}).get(target_currency)
        if converted is None:
            return {"error": f"Could not convert {source_currency} to {target_currency}"}

        rate = round(converted / amount, 8) if amount else 0.0
        return {
            "from": source_currency,
            "to": target_currency,
            "amount": amount,
            "converted": converted,
            "rate": rate,
            "date": data.get("date"),
        }

    @mcp.tool()
    def currency_get_historical(
        date: str,
        base: str = "USD",
    ) -> dict[str, Any]:
        """
        Get exchange rates for a specific historical date.

        Args:
            date: Date in YYYY-MM-DD format (e.g. "2024-01-15")
            base: Base currency code (e.g. "USD"). Default is "USD".

        Returns:
            Dict with base currency, date, and rates on that date.
        """
        normalized_date, error = _parse_historical_date(date)
        if error:
            return error

        normalized_base, error = _normalize_currency_code(base, "base")
        if error:
            return error

        data, error = _request_json(normalized_date, params={"base": normalized_base})
        if error:
            if error.get("status_code") == 404:
                return {"error": f"Unknown currency code: {normalized_base}"}
            if error.get("status_code") == 422:
                return {"error": f"Invalid date: {normalized_date}"}
            return {"error": error["error"]}

        return {
            "base": data.get("base"),
            "date": data.get("date"),
            "rates": data.get("rates", {}),
            "count": len(data.get("rates", {})),
        }
