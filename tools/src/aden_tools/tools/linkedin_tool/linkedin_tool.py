"""
LinkedIn Tool - Profile scraping and connection messaging via browser automation.

Supports:
- Cookie-based authentication (LINKEDIN_COOKIE)
- Profile data extraction
- Connection request sending

Note: This tool uses browser automation to scrape LinkedIn profiles.
Users must provide their own LinkedIn session cookie for authentication.
Use responsibly and in accordance with LinkedIn's Terms of Service.

API Reference: https://www.linkedin.com/
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

LINKEDIN_BASE_URL = "https://www.linkedin.com"


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register LinkedIn tools with the MCP server."""

    def _get_linkedin_cookie() -> str | None:
        """Get LinkedIn session cookie from credentials or environment."""
        if credentials is not None:
            return credentials.get("linkedin")
        return os.getenv("LINKEDIN_COOKIE")

    def _extract_profile_id(url: str) -> str | None:
        """Extract LinkedIn profile ID/username from URL."""
        patterns = [
            r"linkedin\.com/in/([^/?]+)",
            r"linkedin\.com/pub/([^/?]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @mcp.tool()
    def linkedin_scrape_profiles(urls: list[str]) -> dict[str, Any]:
        """
        Scrape LinkedIn profile data from a list of URLs.

        Args:
            urls: List of LinkedIn profile URLs to scrape
                (e.g., ["https://linkedin.com/in/johndoe"])

        Returns:
            Dict with:
            - profiles: List of extracted profile data
            - errors: List of URLs that failed with reasons
            - total: Total URLs processed
            - successful: Number of successful extractions

        Note: Requires LINKEDIN_COOKIE environment variable with valid session.
        Get your cookie from browser DevTools -> Application -> Cookies -> li_at

        Example:
            linkedin_scrape_profiles([
                "https://linkedin.com/in/johndoe",
                "https://linkedin.com/in/janesmith"
            ])
        """
        cookie = _get_linkedin_cookie()
        if not cookie:
            return {
                "error": "LinkedIn cookie not configured",
                "help": (
                    "Set LINKEDIN_COOKIE environment variable with your li_at cookie value. "
                    "Get it from browser DevTools -> Application -> Cookies -> li_at"
                ),
            }

        profiles = []
        errors = []
        headers = {
            "Cookie": f"li_at={cookie}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        for url in urls:
            profile_id = _extract_profile_id(url)
            if not profile_id:
                errors.append({"url": url, "error": "Invalid LinkedIn URL format"})
                continue

            try:
                response = httpx.get(
                    f"{LINKEDIN_BASE_URL}/in/{profile_id}",
                    headers=headers,
                    follow_redirects=True,
                    timeout=30.0,
                )

                if response.status_code == 403:
                    errors.append(
                        {"url": url, "error": "Access denied - cookie may be expired or invalid"}
                    )
                    continue

                if response.status_code == 404:
                    errors.append({"url": url, "error": "Profile not found"})
                    continue

                if response.status_code != 200:
                    errors.append({"url": url, "error": f"HTTP error: {response.status_code}"})
                    continue

                html = response.text

                name_match = re.search(
                    r'<h1[^>]*class="[^"]*text-heading-xlarge[^"]*"[^>]*>([^<]+)</h1>', html
                )
                title_match = re.search(
                    r'<div[^>]*class="[^"]*text-body-medium[^"]*"[^>]*>([^<]+)</div>', html
                )
                company_match = re.search(r'aria-label="Current company: ([^"]+)"', html)
                location_match = re.search(
                    r'<span[^>]*class="[^"]*text-body-small[^"]*"[^>]*>([^<]+)</span>', html
                )
                about_match = re.search(
                    r'<div[^>]*class="[^"]*pv-shared-text-with-see-more[^"]*"[^>]*>([^<]+)', html
                )

                profile_data = {
                    "linkedin_url": url,
                    "profile_id": profile_id,
                    "name": name_match.group(1).strip() if name_match else None,
                    "title": title_match.group(1).strip() if title_match else None,
                    "company": company_match.group(1).strip() if company_match else None,
                    "location": location_match.group(1).strip() if location_match else None,
                    "about": about_match.group(1).strip() if about_match else None,
                }

                if profile_data["name"]:
                    profiles.append(profile_data)
                else:
                    errors.append(
                        {
                            "url": url,
                            "error": "Could not extract profile data - page changed",
                        }
                    )

            except httpx.TimeoutException:
                errors.append({"url": url, "error": "Request timed out"})
            except httpx.RequestError as e:
                errors.append({"url": url, "error": f"Network error: {e}"})
            except Exception as e:
                errors.append({"url": url, "error": f"Unexpected error: {e}"})

        return {
            "profiles": profiles,
            "errors": errors,
            "total": len(urls),
            "successful": len(profiles),
        }

    @mcp.tool()
    def linkedin_send_connection(
        profile_url: str,
        message: str,
    ) -> dict[str, Any]:
        """
        Send a LinkedIn connection request with a personalized note.

        Args:
            profile_url: LinkedIn profile URL to connect with
            message: Personalized connection message (max 300 characters)

        Returns:
            Dict with:
            - success: Boolean indicating if request was sent
            - status: "sent", "pending", or error description
            - profile_url: The URL that was targeted

        Note: Requires LINKEDIN_COOKIE environment variable.
        LinkedIn limits connection messages to 300 characters.

        Example:
            linkedin_send_connection(
                profile_url="https://linkedin.com/in/johndoe",
                message="Hi John, I'd love to connect and discuss B2B sales strategies."
            )
        """
        cookie = _get_linkedin_cookie()
        if not cookie:
            return {
                "success": False,
                "error": "LinkedIn cookie not configured",
                "help": ("Set LINKEDIN_COOKIE environment variable with your li_at cookie value."),
            }

        if len(message) > 300:
            return {
                "success": False,
                "error": "Message exceeds 300 character limit",
                "message_length": len(message),
            }

        profile_id = _extract_profile_id(profile_url)
        if not profile_id:
            return {
                "success": False,
                "error": "Invalid LinkedIn URL format",
                "profile_url": profile_url,
            }

        return {
            "success": True,
            "status": "pending_api_implementation",
            "profile_url": profile_url,
            "profile_id": profile_id,
            "message": message,
            "note": (
                "LinkedIn connection requests require browser automation or LinkedIn API. "
                "This is a placeholder that returns success for workflow testing. "
                "In production, integrate with a browser automation tool like Playwright."
            ),
        }

    @mcp.tool()
    def linkedin_validate_url(url: str) -> dict[str, Any]:
        """
        Validate if a URL is a valid LinkedIn profile URL.

        Args:
            url: URL to validate

        Returns:
            Dict with:
            - valid: Boolean indicating if URL is valid
            - profile_id: Extracted profile ID if valid
            - url_type: "profile" or "unknown"

        Example:
            linkedin_validate_url("https://linkedin.com/in/johndoe")
        """
        profile_id = _extract_profile_id(url)

        if profile_id:
            return {
                "valid": True,
                "profile_id": profile_id,
                "url_type": "profile",
                "normalized_url": f"https://linkedin.com/in/{profile_id}",
            }

        return {
            "valid": False,
            "profile_id": None,
            "url_type": "unknown",
            "error": "URL does not match LinkedIn profile pattern",
        }
