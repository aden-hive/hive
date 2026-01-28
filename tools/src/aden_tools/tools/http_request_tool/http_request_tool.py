"""
HTTP Request Tool - Make HTTP requests to any URL.

Supports all HTTP methods, custom headers, JSON/form bodies,
query parameters, and configurable timeouts.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialManager


# Hosts that are blocked by default to prevent SSRF attacks
BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata endpoint
    "metadata.google.internal",  # GCP metadata
}

# Private IP ranges to block (SSRF protection)
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),  # IPv6 localhost
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private IP address."""
    try:
        # Try to parse as IP address directly
        ip = ipaddress.ip_address(hostname)
        return any(ip in network for network in PRIVATE_IP_RANGES)
    except ValueError:
        # Not an IP address, try to resolve hostname
        try:
            ip_str = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(ip_str)
            return any(ip in network for network in PRIVATE_IP_RANGES)
        except socket.gaierror:
            # Can't resolve hostname - allow it (will fail later if invalid)
            return False


def register_tools(
    mcp: FastMCP,
    credentials: CredentialManager | None = None,
) -> None:
    """Register HTTP request tools with the MCP server."""

    @mcp.tool()
    def http_request(
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str | None = None,
        json_body: dict | None = None,
        params: dict | None = None,
        timeout: int = 30,
        follow_redirects: bool = True,
        allow_private_ips: bool = False,
    ) -> dict:
        """
        Make an HTTP request to any URL.

        Use this for calling REST APIs, webhooks, or any HTTP endpoint.
        Returns status code, headers, and response body.

        Args:
            url: The full URL to request (must start with http:// or https://)
            method: HTTP method - GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
            headers: Optional dict of HTTP headers (e.g., {"Authorization": "Bearer token"})
            body: Raw request body as string
            json_body: Request body as dict (will be JSON-encoded, sets Content-Type)
            params: Query parameters as dict (appended to URL)
            timeout: Request timeout in seconds (1-120, default 30)
            follow_redirects: Whether to follow HTTP redirects (default True)
            allow_private_ips: Allow requests to private/internal IPs (default False, for security)

        Returns:
            Dict with status_code, headers, body, is_json, elapsed_ms on success.
            Dict with error key on failure.
        """
        # Validate URL
        if not url:
            return {"error": "URL is required"}

        try:
            parsed = urlparse(url)
        except Exception:
            return {"error": "Invalid URL format"}

        # Validate scheme
        if parsed.scheme not in ("http", "https"):
            return {"error": "URL must start with http:// or https://"}

        # Validate hostname exists
        if not parsed.hostname:
            return {"error": "URL must include a hostname"}

        # Security: Block dangerous hosts
        hostname_lower = parsed.hostname.lower()
        if hostname_lower in BLOCKED_HOSTS:
            return {"error": f"Requests to {parsed.hostname} are not allowed"}

        # Security: Block private IPs (unless explicitly allowed)
        if not allow_private_ips and _is_private_ip(parsed.hostname):
            return {
                "error": "Requests to private/internal IP addresses are not allowed. "
                "Set allow_private_ips=True to override."
            }

        # Validate method
        method = method.upper().strip()
        if method not in ALLOWED_METHODS:
            return {
                "error": f"Invalid HTTP method: {method}. "
                f"Allowed: {', '.join(sorted(ALLOWED_METHODS))}"
            }

        # Validate and clamp timeout
        if not isinstance(timeout, (int, float)):
            timeout = 30
        timeout = max(1, min(120, int(timeout)))

        # Validate body - can't have both body and json_body
        if body is not None and json_body is not None:
            return {"error": "Cannot specify both 'body' and 'json_body'. Use one or the other."}

        # Prepare request kwargs
        request_kwargs = {
            "method": method,
            "url": url,
            "timeout": float(timeout),
            "follow_redirects": follow_redirects,
        }

        # Add headers
        if headers:
            if not isinstance(headers, dict):
                return {"error": "headers must be a dict"}
            request_kwargs["headers"] = headers

        # Add query params
        if params:
            if not isinstance(params, dict):
                return {"error": "params must be a dict"}
            request_kwargs["params"] = params

        # Add body
        if json_body is not None:
            if not isinstance(json_body, dict):
                return {"error": "json_body must be a dict"}
            request_kwargs["json"] = json_body
        elif body is not None:
            if not isinstance(body, str):
                return {"error": "body must be a string"}
            request_kwargs["content"] = body

        # Make the request
        try:
            with httpx.Client() as client:
                response = client.request(**request_kwargs)

            # Parse response headers
            response_headers = dict(response.headers)

            # Determine if response is JSON
            content_type = response_headers.get("content-type", "")
            is_json = "application/json" in content_type.lower()

            # Parse response body
            if is_json:
                try:
                    response_body = response.json()
                except json.JSONDecodeError:
                    response_body = response.text
                    is_json = False
            else:
                # For non-JSON, return text (limit size to prevent memory issues)
                response_body = response.text
                if len(response_body) > 1_000_000:  # 1MB limit
                    truncated_msg = "\n... [truncated, response exceeded 1MB]"
                    response_body = response_body[:1_000_000] + truncated_msg

            return {
                "status_code": response.status_code,
                "headers": response_headers,
                "body": response_body,
                "is_json": is_json,
                "elapsed_ms": int(response.elapsed.total_seconds() * 1000),
            }

        except httpx.TimeoutException:
            return {"error": f"Request timed out after {timeout} seconds"}
        except httpx.TooManyRedirects:
            return {"error": "Too many redirects (exceeded limit)"}
        except httpx.ConnectError as e:
            return {"error": f"Connection failed: {str(e)}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
