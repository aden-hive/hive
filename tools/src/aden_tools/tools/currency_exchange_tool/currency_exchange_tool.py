"""
Currency Exchange Rate Tool - Fetch real-time and historical exchange rates.

This tool integrates with the ExchangeRate-API (https://exchangerate-api.com)
to provide currency conversion and exchange rate data for AI agents handling
financial workflows, invoicing, and international business operations.

Supports:
- Fetching latest exchange rates for any base currency
- Converting an amount from one currency to another
- Listing all supported currencies

Authentication:
    Requires a free API key from https://exchangerate-api.com
    Free tier: 1,500 requests/month, no credit card required

Environment Variables:
    EXCHANGERATE_API_KEY: Your ExchangeRate-API key

API Reference: https://www.exchangerate-api.com/docs/overview
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Base URL for ExchangeRate-API v6
EXCHANGERATE_API_BASE = "https://v6.exchangerate-api.com/v6"


class _CurrencyExchangeClient:
    """
    Internal HTTP client for the ExchangeRate-API.

    Wraps all API calls and handles response validation,
    error mapping, and rate limit detection.
    """

    def __init__(self, api_key: str):
        """
        Initialize the client with an API key.

        Args:
            api_key: ExchangeRate-API key from exchangerate-api.com
        """
        self._api_key = api_key

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        Validate and parse an API response.

        Handles HTTP-level errors and API-level error codes
        returned in the JSON body.

        Args:
            response: The raw httpx response object

        Returns:
            Parsed JSON dict, or a dict with an 'error' key on failure
        """
        # Handle HTTP-level errors
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Free tier allows 1,500 requests/month."}
        if response.status_code == 401:
            return {"error": "Invalid API key. Check your EXCHANGERATE_API_KEY."}
        if response.status_code not in (200, 201):
            return {"error": f"HTTP error {response.status_code}: {response.text}"}

        data = response.json()

        # Handle API-level errors returned in the response body
        if data.get("result") == "error":
            error_type = data.get("error-type", "unknown-error")
            error_messages = {
                "unsupported-code": "Currency code is not supported.",
                "malformed-request": "Request is malformed. Check parameters.",
                "invalid-key": "Invalid API key.",
                "inactive-account": "Account is inactive. Check your email.",
                "quota-reached": "Monthly request quota reached.",
            }
            return {
                "error": error_messages.get(error_type, f"API error: {error_type}"),
                "error_type": error_type,
            }

        return data

    def get_latest_rates(self, base_currency: str) -> dict[str, Any]:
        """
        Fetch the latest exchange rates for a given base currency.

        Args:
            base_currency: ISO 4217 currency code (e.g., 'USD', 'EUR', 'INR')

        Returns:
            Dict containing exchange rates for all supported currencies
        """
        response = httpx.get(
            f"{EXCHANGERATE_API_BASE}/{self._api_key}/latest/{base_currency.upper()}",
            timeout=30.0,
        )
        return self._handle_response(response)

    def convert_currency(
        self,
        from_currency: str,
        to_currency: str,
        amount: float,
    ) -> dict[str, Any]:
        """
        Convert an amount from one currency to another.

        Args:
            from_currency: Source currency ISO code (e.g., 'USD')
            to_currency: Target currency ISO code (e.g., 'INR')
            amount: Amount to convert (must be positive)

        Returns:
            Dict with conversion result and exchange rate used
        """
        response = httpx.get(
            f"{EXCHANGERATE_API_BASE}/{self._api_key}/pair/"
            f"{from_currency.upper()}/{to_currency.upper()}/{amount}",
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_supported_currencies(self) -> dict[str, Any]:
        """
        Fetch the list of all currencies supported by the API.

        Returns:
            Dict mapping currency codes to currency names
        """
        response = httpx.get(
            f"{EXCHANGERATE_API_BASE}/{self._api_key}/codes",
            timeout=30.0,
        )
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
) -> None:
    """
    Register Currency Exchange tools with the MCP server.

    This function registers 3 tools:
    - currency_exchange_get_rates
    - currency_exchange_convert
    - currency_exchange_list_currencies

    Args:
        mcp: FastMCP server instance to register tools on
    """

    def _get_api_key() -> str | None:
        """
        Retrieve the API key from credential store or environment variable.

        Returns:
            API key string, or None if not configured
        """
        return os.getenv("EXCHANGERATE_API_KEY")

    def _get_client() -> _CurrencyExchangeClient | dict[str, str]:
        """
        Build a client instance, or return an error dict if unconfigured.

        Returns:
            Configured _CurrencyExchangeClient, or error dict
        """
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Currency Exchange credentials not configured",
                "help": (
                    "Set the EXCHANGERATE_API_KEY environment variable. "
                    "Get a free key at https://exchangerate-api.com"
                ),
            }
        return _CurrencyExchangeClient(api_key=api_key)

    @mcp.tool()
    def currency_exchange_get_rates(base_currency: str) -> dict:
        """
        Get the latest exchange rates for a base currency.

        Fetches real-time exchange rates relative to the given base currency
        for all ~160 supported currencies.

        Args:
            base_currency: ISO 4217 base currency code (e.g., 'USD', 'EUR', 'INR')

        Returns:
            Dict with:
                - base_currency: The base currency used
                - last_updated: Unix timestamp of last rate update
                - rates: Dict mapping currency codes to exchange rates
            Or error dict if request fails.

        Example:
            currency_exchange_get_rates("USD")
            # Returns rates like {"USD": 1.0, "EUR": 0.92, "INR": 83.5, ...}
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_latest_rates(base_currency)
            if "error" in result:
                return result
            return {
                "success": True,
                "base_currency": result.get("base_code"),
                "last_updated": result.get("time_last_update_unix"),
                "rates": result.get("conversion_rates", {}),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out. Try again."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def currency_exchange_convert(
        from_currency: str,
        to_currency: str,
        amount: float,
    ) -> dict:
        """
        Convert an amount from one currency to another.

        Uses real-time exchange rates to calculate the converted amount.
        Useful for invoicing, financial reporting, and international pricing.

        Args:
            from_currency: Source currency ISO code (e.g., 'USD')
            to_currency: Target currency ISO code (e.g., 'INR')
            amount: Amount to convert. Must be greater than 0.

        Returns:
            Dict with:
                - from_currency: Source currency code
                - to_currency: Target currency code
                - original_amount: The input amount
                - converted_amount: Result after conversion
                - exchange_rate: Rate used for conversion
                - last_updated: Unix timestamp of rate data
            Or error dict if request fails.

        Example:
            currency_exchange_convert("USD", "INR", 100)
            # Returns {"converted_amount": 8350.0, "exchange_rate": 83.5, ...}
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        if amount <= 0:
            return {"error": "Amount must be greater than 0"}
        try:
            result = client.convert_currency(from_currency, to_currency, amount)
            if "error" in result:
                return result
            return {
                "success": True,
                "from_currency": result.get("base_code"),
                "to_currency": result.get("target_code"),
                "original_amount": amount,
                "converted_amount": result.get("conversion_result"),
                "exchange_rate": result.get("conversion_rate"),
                "last_updated": result.get("time_last_update_unix"),
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out. Try again."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def currency_exchange_list_currencies() -> dict:
        """
        List all currencies supported by the exchange rate API.

        Returns a complete list of supported ISO 4217 currency codes
        and their full names. Useful for validating currency codes
        before making conversion requests.

        Returns:
            Dict with:
                - count: Total number of supported currencies
                - currencies: List of dicts with 'code' and 'name' fields
            Or error dict if request fails.

        Example:
            currency_exchange_list_currencies()
            # Returns [{"code": "USD", "name": "US Dollar"}, ...]
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            result = client.get_supported_currencies()
            if "error" in result:
                return result
            supported = result.get("supported_codes", [])
            currencies = [
                {"code": code, "name": name}
                for code, name in supported
            ]
            return {
                "success": True,
                "count": len(currencies),
                "currencies": currencies,
            }
        except httpx.TimeoutException:
            return {"error": "Request timed out. Try again."}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
