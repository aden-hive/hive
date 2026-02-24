"""
HTTP Headers Scanner - Check OWASP-recommended security headers.

Performs a non-intrusive HTTP request and evaluates the presence and
configuration of security headers per OWASP Secure Headers Project guidelines.
"""

from __future__ import annotations

import httpx
from fastmcp import FastMCP

# Security headers to check — each with severity and remediation guidance
SECURITY_HEADERS = {
    "Strict-Transport-Security": {
        "severity": "high",
        "description": (
            "No HSTS header. Browsers may connect over plain HTTP, "
            "enabling man-in-the-middle attacks."
        ),
        "remediation": (
            "Add the header: Strict-Transport-Security: max-age=31536000; includeSubDomains"
        ),
    },
    "Content-Security-Policy": {
        "severity": "high",
        "description": (
            "No CSP header. The site is more vulnerable to XSS attacks "
            "from inline scripts and untrusted sources."
        ),
        "remediation": (
            "Add a Content-Security-Policy header. "
            "Start restrictive: default-src 'self'; script-src 'self'"
        ),
    },
    "X-Frame-Options": {
        "severity": "medium",
        "description": ("No X-Frame-Options header. The site may be vulnerable to clickjacking."),
        "remediation": "Add the header: X-Frame-Options: DENY (or SAMEORIGIN)",
    },
    "X-Content-Type-Options": {
        "severity": "medium",
        "description": (
            "No X-Content-Type-Options header. Browsers may MIME-sniff responses, "
            "potentially executing malicious content."
        ),
        "remediation": "Add the header: X-Content-Type-Options: nosniff",
    },
    "Referrer-Policy": {
        "severity": "low",
        "description": (
            "No Referrer-Policy header. Full URLs (including query params) "
            "may leak to third-party sites via the Referer header."
        ),
        "remediation": ("Add the header: Referrer-Policy: strict-origin-when-cross-origin"),
    },
    "Permissions-Policy": {
        "severity": "low",
        "description": (
            "No Permissions-Policy header. Browser features like camera, microphone, "
            "and geolocation are not explicitly restricted."
        ),
        "remediation": (
            "Add the header: Permissions-Policy: camera=(), microphone=(), geolocation=()"
        ),
    },
}

# Headers that leak server information
LEAKY_HEADERS = {
    "Server": {
        "severity": "low",
        "remediation": "Remove or genericize the Server header to avoid version disclosure.",
    },
    "X-Powered-By": {
        "severity": "low",
        "remediation": "Remove the X-Powered-By header to hide the backend framework.",
    },
    "X-AspNet-Version": {
        "severity": "low",
        "remediation": "Remove the X-AspNet-Version header from IIS/ASP.NET configuration.",
    },
    "X-AspNetMvc-Version": {
        "severity": "low",
        "remediation": "Remove the X-AspNetMvc-Version header.",
    },
    "X-Generator": {
        "severity": "low",
        "remediation": "Remove the X-Generator header to hide the CMS/platform in use.",
    },
}


def register_tools(mcp: FastMCP) -> None:
    """Register HTTP headers scanning tools with the MCP server."""

    @mcp.tool()
    async def http_headers_scan(url: str, follow_redirects: bool = True) -> dict:
        """
        Scan a URL for OWASP-recommended security headers and information leaks.

        Sends a single GET request and evaluates response headers against
        OWASP Secure Headers Project guidelines. Non-intrusive — just one request.

        Args:
            url: Full URL to scan (e.g., "https://example.com"). Auto-prefixes https://.
            follow_redirects: Whether to follow HTTP redirects (default True).

        Returns:
            Dict with present headers, missing headers with remediation,
            leaky headers, and grade_input for the risk_scorer tool.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            async with httpx.AsyncClient(
                follow_redirects=follow_redirects,
                timeout=15,
                verify=True,
            ) as client:
                response = await client.get(url)
        except httpx.ConnectError as e:
            return {"error": f"Connection failed: {e}"}
        except httpx.TimeoutException:
            return {"error": f"Request to {url} timed out"}
        except Exception as e:
            return {"error": f"Request failed: {e}"}

        headers = response.headers
        headers_present = []
        headers_missing = []

        # Check each security header
        for header_name, info in SECURITY_HEADERS.items():
            if header_name.lower() in {k.lower() for k in headers}:
                headers_present.append(header_name)
            else:
                headers_missing.append(
                    {
                        "header": header_name,
                        "severity": info["severity"],
                        "description": info["description"],
                        "remediation": info["remediation"],
                    }
                )

        # Check for leaky headers
        leaky_found = []
        for header_name, info in LEAKY_HEADERS.items():
            value = headers.get(header_name)
            if value:
                leaky_found.append(
                    {
                        "header": header_name,
                        "value": value,
                        "severity": info["severity"],
                        "remediation": info["remediation"],
                    }
                )

        # Check for deprecated X-XSS-Protection
        xss_protection = headers.get("X-XSS-Protection")
        if xss_protection:
            headers_present.append("X-XSS-Protection (deprecated)")

        # Build grade_input
        header_lower = {k.lower() for k in headers}
        grade_input = {
            "hsts": "strict-transport-security" in header_lower,
            "csp": "content-security-policy" in header_lower,
            "x_frame_options": "x-frame-options" in header_lower,
            "x_content_type_options": "x-content-type-options" in header_lower,
            "referrer_policy": "referrer-policy" in header_lower,
            "permissions_policy": "permissions-policy" in header_lower,
            "no_leaky_headers": len(leaky_found) == 0,
        }

        return {
            "url": str(response.url),
            "status_code": response.status_code,
            "headers_present": headers_present,
            "headers_missing": headers_missing,
            "leaky_headers": leaky_found,
            "grade_input": grade_input,
        }
