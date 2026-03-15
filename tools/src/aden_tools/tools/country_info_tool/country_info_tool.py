"""
Country Info Tool - Free country data via restcountries.com.

Provides country data including currencies, languages, timezones,
calling codes, and flags. No API key required.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP

_BASE_URL = "https://restcountries.com/v3.1"
_FIELDS = (
    "name,cca2,cca3,currencies,languages,timezones,idd,flags,population,"
    "capital,region,subregion"
)


def _simplify_country(data: dict) -> dict:
    """Extract the most useful fields from a restcountries response object."""
    currencies = {
        code: info.get("name", code)
        for code, info in (data.get("currencies") or {}).items()
    }
    languages = list((data.get("languages") or {}).values())
    calling_codes: list[str] = []
    idd = data.get("idd") or {}
    root = idd.get("root", "")
    suffixes = idd.get("suffixes") or []
    if root and suffixes:
        calling_codes = [f"{root}{s}" for s in suffixes]
    elif root:
        calling_codes = [root]

    return {
        "name": (data.get("name") or {}).get("common", ""),
        "official_name": (data.get("name") or {}).get("official", ""),
        "cca2": data.get("cca2", ""),
        "cca3": data.get("cca3", ""),
        "capital": (data.get("capital") or [None])[0],
        "region": data.get("region", ""),
        "subregion": data.get("subregion", ""),
        "population": data.get("population", 0),
        "currencies": currencies,
        "languages": languages,
        "timezones": data.get("timezones") or [],
        "calling_codes": calling_codes,
        "flag_emoji": (data.get("flags") or {}).get("alt", ""),
        "flag_png": (data.get("flags") or {}).get("png", ""),
    }


def register_tools(mcp: FastMCP) -> None:
    """Register country info tools with the MCP server."""

    @mcp.tool()
    def country_get_by_name(name: str, full_text: bool = False) -> dict:
        """
        Get country data by country name.

        Args:
            name: Country name to search for (e.g. "Germany", "United States").
            full_text: If True, only exact full-name matches are returned.
                       If False (default), partial matches are included.

        Returns:
            Dictionary with a "countries" list. Each entry contains:
            - name, official_name: common and official country names
            - cca2, cca3: ISO 2- and 3-letter codes
            - capital, region, subregion, population
            - currencies: {code: name} mapping
            - languages: list of language names
            - timezones: list of timezone strings
            - calling_codes: list of phone prefixes
            - flag_emoji, flag_png: flag description and PNG URL
        """
        try:
            params = {"fields": _FIELDS}
            if full_text:
                params["fullText"] = "true"
            resp = httpx.get(
                f"{_BASE_URL}/name/{name}",
                params=params,
                timeout=10.0,
            )
            if resp.status_code == 404:
                return {"error": f"No country found matching name: {name!r}"}
            resp.raise_for_status()
            return {"countries": [_simplify_country(c) for c in resp.json()]}
        except httpx.HTTPStatusError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def country_get_by_code(code: str) -> dict:
        """
        Get country data by ISO alpha-2 or alpha-3 code.

        Args:
            code: ISO 3166-1 alpha-2 (e.g. "DE") or alpha-3 (e.g. "DEU") country code.
                  Case-insensitive.

        Returns:
            Dictionary with a "country" key containing the same fields as
            country_get_by_name, or an "error" key on failure.
        """
        try:
            resp = httpx.get(
                f"{_BASE_URL}/alpha/{code}",
                params={"fields": _FIELDS},
                timeout=10.0,
            )
            if resp.status_code == 404:
                return {"error": f"No country found for code: {code!r}"}
            resp.raise_for_status()
            data = resp.json()
            # API returns a list when given /alpha/{code}
            if isinstance(data, list):
                data = data[0]
            return {"country": _simplify_country(data)}
        except httpx.HTTPStatusError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def country_get_by_currency(currency_code: str) -> dict:
        """
        Find all countries that use a specific currency.

        Args:
            currency_code: ISO 4217 currency code (e.g. "EUR", "USD", "GBP").
                           Case-insensitive.

        Returns:
            Dictionary with a "countries" list of country objects that use the
            specified currency, or an "error" key on failure.
        """
        try:
            resp = httpx.get(
                f"{_BASE_URL}/currency/{currency_code}",
                params={"fields": _FIELDS},
                timeout=10.0,
            )
            if resp.status_code == 404:
                return {"error": f"No countries found using currency: {currency_code!r}"}
            resp.raise_for_status()
            return {"countries": [_simplify_country(c) for c in resp.json()]}
        except httpx.HTTPStatusError as exc:
            return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
        except Exception as exc:
            return {"error": str(exc)}
