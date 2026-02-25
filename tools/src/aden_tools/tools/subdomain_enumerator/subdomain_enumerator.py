"""
Subdomain Enumerator - Discover subdomains via Certificate Transparency logs.

Performs passive subdomain discovery by querying crt.sh (Certificate Transparency
log aggregator). No active brute-forcing or DNS enumeration — fully OSINT-based.
"""

from __future__ import annotations

import re

import httpx
from fastmcp import FastMCP

# Subdomain keywords that indicate potentially sensitive environments
INTERESTING_KEYWORDS = {
    "staging": {
        "reason": "Staging environment exposed publicly",
        "severity": "medium",
        "remediation": "Restrict staging to VPN or internal network access.",
    },
    "dev": {
        "reason": "Development environment exposed publicly",
        "severity": "medium",
        "remediation": "Restrict development servers to internal access only.",
    },
    "test": {
        "reason": "Test environment exposed publicly",
        "severity": "medium",
        "remediation": "Restrict test servers to internal access only.",
    },
    "admin": {
        "reason": "Admin panel subdomain exposed publicly",
        "severity": "high",
        "remediation": "Restrict admin panels to VPN or trusted IP ranges.",
    },
    "internal": {
        "reason": "Internal subdomain exposed in CT logs",
        "severity": "medium",
        "remediation": "Review if internal subdomains should have public certificates.",
    },
    "vpn": {
        "reason": "VPN endpoint discoverable via CT logs",
        "severity": "low",
        "remediation": "Consider if VPN endpoint exposure is acceptable for your threat model.",
    },
    "api": {
        "reason": "API subdomain discovered — potential attack surface",
        "severity": "low",
        "remediation": "Ensure API is properly authenticated and rate-limited.",
    },
    "mail": {
        "reason": "Mail server subdomain discovered",
        "severity": "info",
        "remediation": "Ensure mail server has proper SPF, DKIM, and DMARC configuration.",
    },
    "ftp": {
        "reason": "FTP subdomain discovered — legacy protocol",
        "severity": "medium",
        "remediation": "Replace FTP with SFTP. Restrict access to trusted networks.",
    },
    "debug": {
        "reason": "Debug subdomain exposed publicly",
        "severity": "high",
        "remediation": "Remove debug endpoints from production. Restrict to internal access.",
    },
    "backup": {
        "reason": "Backup subdomain exposed publicly",
        "severity": "high",
        "remediation": "Restrict backup infrastructure to internal access only.",
    },
}


def register_tools(mcp: FastMCP) -> None:
    """Register subdomain enumeration tools with the MCP server."""

    @mcp.tool()
    async def subdomain_enumerate(domain: str, max_results: int = 50) -> dict:
        """
        Discover subdomains using Certificate Transparency (CT) logs.

        Queries crt.sh to find all certificates issued for a domain, extracting
        subdomain names. Fully passive — uses only public CT log data.
        Flags potentially interesting subdomains (staging, dev, admin, etc.).

        Args:
            domain: Base domain to enumerate (e.g., "example.com"). No protocol prefix.
            max_results: Maximum number of subdomains to return (default 50, max 200).

        Returns:
            Dict with discovered subdomains, interesting findings,
            and grade_input for the risk_scorer tool.
        """
        # Clean domain
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        domain = domain.split("/")[0]
        if ":" in domain:
            domain = domain.split(":")[0]

        max_results = min(max_results, 200)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://crt.sh/",
                    params={"q": f"%.{domain}", "output": "json"},
                )

                if response.status_code != 200:
                    return {
                        "error": f"crt.sh returned HTTP {response.status_code}",
                        "domain": domain,
                    }

                data = response.json()

        except httpx.TimeoutException:
            return {"error": "crt.sh request timed out (try again later)", "domain": domain}
        except Exception as e:
            return {"error": f"CT log query failed: {e}", "domain": domain}

        # Extract unique subdomains
        raw_names: set[str] = set()
        for entry in data:
            name_value = entry.get("name_value", "")
            # Can contain multiple names separated by newlines
            for name in name_value.split("\n"):
                name = name.strip().lower()
                if name and name.endswith(f".{domain}") or name == domain:
                    raw_names.add(name)

        # Filter out wildcards and deduplicate
        subdomains = sorted(
            {name for name in raw_names if not name.startswith("*.")},
        )

        # Limit results
        subdomains = subdomains[:max_results]

        # Identify interesting subdomains
        interesting = []
        for sub in subdomains:
            # Get the subdomain prefix (everything before the base domain)
            prefix = sub.replace(f".{domain}", "").lower()
            for keyword, info in INTERESTING_KEYWORDS.items():
                if re.search(rf"\b{keyword}\b", prefix) or prefix == keyword:
                    interesting.append(
                        {
                            "subdomain": sub,
                            "reason": info["reason"],
                            "severity": info["severity"],
                            "remediation": info["remediation"],
                        }
                    )
                    break

        # Grade input
        has_dev_staging = any(
            i["severity"] in ("medium", "high")
            and any(kw in i["subdomain"] for kw in ("staging", "dev", "test", "debug"))
            for i in interesting
        )
        has_admin = any(
            any(kw in i["subdomain"] for kw in ("admin", "backup")) for i in interesting
        )
        # "reasonable" = fewer than 50 subdomains
        reasonable_surface = len(subdomains) < 50

        grade_input = {
            "no_dev_staging_exposed": not has_dev_staging,
            "no_admin_exposed": not has_admin,
            "reasonable_surface_area": reasonable_surface,
        }

        return {
            "domain": domain,
            "source": "crt.sh (Certificate Transparency)",
            "total_found": len(subdomains),
            "subdomains": subdomains,
            "interesting": interesting,
            "grade_input": grade_input,
        }
