"""Cloudflare DNS/Zone management tool integration.

Provides full management access to Cloudflare zones and DNS records for domain
troubleshooting, deployment verification, and infrastructure automation.

Uses the Cloudflare REST API with Bearer token authentication.
Requires CLOUDFLARE_API_TOKEN environment variable.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# Cloudflare API configuration
CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
HEALTH_CHECK_TIMEOUT = 30


def _get_token(credentials=None) -> str | dict:
    """Get Cloudflare API token from environment or credential store.

    Returns:
        str: API token if found
        dict: Error dict if token is missing
    """
    if credentials:
        token = credentials.get("cloudflare")
        if token:
            return token

    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        return {
            "error": "CLOUDFLARE_API_TOKEN is required",
            "help": "Set CLOUDFLARE_API_TOKEN env var or configure credential store",
        }
    return token


def _headers(token: str) -> dict:
    """Build request headers for Cloudflare API."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _validate_zone_id(zone_id: str) -> dict | None:
    """Validate zone_id format. Returns error dict if invalid, None if valid."""
    if not zone_id or not isinstance(zone_id, str):
        return {"error": "zone_id must be a non-empty string"}
    if len(zone_id) != 32 or not all(c in "0123456789abcdef" for c in zone_id.lower()):
        return {"error": f"Invalid zone_id format: {zone_id}"}
    return None


def _validate_domain(domain: str) -> dict | None:
    """Validate domain format. Returns error dict if invalid, None if valid."""
    if not domain or not isinstance(domain, str):
        return {"error": "domain must be a non-empty string"}
    domain = domain.lower().strip()
    if len(domain) < 3 or len(domain) > 255:
        return {"error": f"Domain length must be 3-255 characters: {domain}"}
    if not all(c in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in domain):
        return {"error": f"Invalid domain format: {domain}"}
    return None


def _make_request(
    method: str,
    endpoint: str,
    token: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make HTTP request to Cloudflare API.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path (e.g., "/zones")
        token: Cloudflare API token
        params: Query parameters
        json_data: JSON body data

    Returns:
        dict: Response data or error dict
    """
    url = f"{CLOUDFLARE_API_BASE_URL}{endpoint}"

    try:
        response = httpx.request(
            method,
            url,
            headers=_headers(token),
            params=params,
            json=json_data,
            timeout=HEALTH_CHECK_TIMEOUT,
        )

        # Handle HTTP errors
        if response.status_code == 401:
            return {
                "error": "Unauthorized - invalid or missing CLOUDFLARE_API_TOKEN",
                "status_code": 401,
            }
        elif response.status_code == 403:
            return {
                "error": "Forbidden - token lacks required permissions (Zone/DNS read or edit)",
                "status_code": 403,
            }
        elif response.status_code == 404:
            return {"error": "Not found", "status_code": 404}
        elif response.status_code == 429:
            return {
                "error": "Too many requests - rate limited",
                "status_code": 429,
                "retry_after": response.headers.get("Retry-After"),
            }
        elif response.status_code == 204:  # Handle No Content (common in DELETE)
            return {"success": True, "message": "Operation completed successfully"}
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                error_msg = errors[0].get("message") if errors else response.text[:500]
            except Exception:
                error_msg = response.text[:500]
            return {
                "error": f"HTTP {response.status_code}: {error_msg}",
                "status_code": response.status_code,
            }

        # Parse successful response
        if response.status_code == 204:
            return {"success": True}

        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            error_msg = errors[0].get("message") if errors else "Unknown error"
            return {"error": error_msg}

        return data.get("result", {})

    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


def register_tools(mcp, credentials=None):
    """Register Cloudflare management tools with the MCP server."""

    # --- INFRASTRUCTURE & ZONE MANAGEMENT ---
    # Tools for listing and retrieving basic domain (zone) information

    @mcp.tool("cloudflare_list_zones")
    def cloudflare_list_zones(
        page: int = 1, per_page: int = 20, name: str | None = None
    ) -> dict[str, Any]:
        """List Cloudflare zones (domains) in the account.

        Args:
            page: Page number for pagination (1-indexed)
            per_page: Results per page (1-100, default 20)
            name: Optional zone name filter

        Returns:
            dict with zones list and pagination info
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        # Validate pagination params
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), MAX_PAGE_SIZE))

        params = {"page": page, "per_page": per_page}
        if name:
            params["name"] = name.strip()

        result = _make_request("GET", "/zones", token, params=params)

        if "error" in result:
            return result

        # Extract and normalize zone data
        zones = (
            result.get("zones", [])
            if isinstance(result, dict) and "zones" not in result
            else result
        )
        if not isinstance(zones, list):
            zones = [result] if isinstance(result, dict) and "id" in result else []

        normalized_zones = [
            {
                "id": z.get("id"),
                "name": z.get("name"),
                "status": z.get("status"),
                "name_servers": z.get("name_servers", []),
                "plan": z.get("plan", {}).get("name"),
            }
            for z in zones
        ]

        return {
            "zones": normalized_zones,
            "page": page,
            "per_page": per_page,
            "total": len(normalized_zones),
        }

    @mcp.tool("cloudflare_get_zone")
    def cloudflare_get_zone(zone_id: str) -> dict[str, Any]:
        """Get details for a specific Cloudflare zone.

        Args:
            zone_id: Zone ID (32-character hex string)

        Returns:
            dict with zone details or error
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}", token)

        if "error" in result:
            return result

        # Normalize zone data
        zone = result if isinstance(result, dict) else {}

        return {
            "id": zone.get("id"),
            "name": zone.get("name"),
            "status": zone.get("status"),
            "name_servers": zone.get("name_servers", []),
            "created_on": zone.get("created_on"),
            "modified_on": zone.get("modified_on"),
            "plan": zone.get("plan", {}).get("name"),
            "type": zone.get("type"),
        }

    @mcp.tool("cloudflare_get_zone_settings")
    def cloudflare_get_zone_settings(zone_id: str) -> dict[str, Any]:
        """Get all common settings for a zone (TLS, IPv6, WebSockets, etc.).

        Args:
            zone_id: Zone ID

        Returns:
            dict with comprehensive zone settings
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/settings", token)
        if "error" in result:
            return result

        settings = result if isinstance(result, list) else result
        return {"settings": settings}

    @mcp.tool("cloudflare_list_zone_custom_pages")
    def cloudflare_list_zone_custom_pages(zone_id: str) -> dict[str, Any]:
        """List custom error and challenge pages for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of custom pages and their URLs
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/custom_pages", token)
        if "error" in result:
            return result

        pages = result if isinstance(result, list) else []
        return {"custom_pages": pages}

    @mcp.tool("cloudflare_get_ssl_verification")
    def cloudflare_get_ssl_verification(zone_id: str) -> dict[str, Any]:
        """Get SSL certificate verification status for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            SSL verification details and pending actions
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/ssl/verification", token)
        if "error" in result:
            return result

        verification = result if isinstance(result, list) else result
        return {"ssl_verification": verification}

    @mcp.tool("cloudflare_list_zone_certificates")
    def cloudflare_list_zone_certificates(zone_id: str) -> dict[str, Any]:
        """List all SSL/TLS certificates for a zone (Origin, Universal, Custom).

        Args:
            zone_id: Zone ID

        Returns:
            list of certificates with expiry and issuer info
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Get universal SSL status and custom certificates
        universal = _make_request("GET", f"/zones/{zone_id}/ssl/universal/settings", token)
        custom = _make_request("GET", f"/zones/{zone_id}/custom_certificates", token)

        return {
            "universal_ssl": universal,
            "custom_certificates": custom if isinstance(custom, list) else [],
        }

    @mcp.tool("cloudflare_list_zone_subscriptions")
    def cloudflare_list_zone_subscriptions(zone_id: str) -> dict[str, Any]:
        """List active paid subscriptions/apps for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of active subscriptions
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/subscriptions", token)
        if "error" in result:
            return result

        subscriptions = result if isinstance(result, list) else []
        return {"subscriptions": subscriptions}

    @mcp.tool("cloudflare_get_dnssec_status")
    def cloudflare_get_dnssec_status(zone_id: str) -> dict[str, Any]:
        """Get DNSSEC status and configuration for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            DNSSEC status and DS records
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/dnssec", token)
        if "error" in result:
            return result

        return {"dnssec": result}

    @mcp.tool("cloudflare_update_zone_setting")
    def cloudflare_update_zone_setting(zone_id: str, setting_id: str, value: Any) -> dict[str, Any]:
        """Update a specific zone setting (IPv6, WebSockets, etc.).

        Args:
            zone_id: Zone ID
            setting_id: Name of the setting (e.g., 'ipv6', 'websockets', 'ssl')
            value: New value for the setting ('on', 'off', or specific values)

        Returns:
            Updated setting details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request(
            "PATCH", f"/zones/{zone_id}/settings/{setting_id}", token, json_data={"value": value}
        )
        return {"updated_setting": result}

    # --- DNS MANAGEMENT ---
    # Tools for listing and retrieving DNS records (A, CNAME, TXT, etc.)

    @mcp.tool("cloudflare_list_dns_records")
    def cloudflare_list_dns_records(
        zone_id: str,
        name: str | None = None,
        type: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """List DNS records for a zone.

        Args:
            zone_id: Zone ID
            name: Optional DNS record name filter
            type: Optional DNS record type filter (A, AAAA, CNAME, MX, TXT, etc.)
            page: Page number for pagination
            per_page: Results per page (1-100, default 20)

        Returns:
            dict with records list and pagination info
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Validate pagination
        page = max(1, int(page))
        per_page = max(1, min(int(per_page), MAX_PAGE_SIZE))

        # Build query params
        params = {"page": page, "per_page": per_page}
        if name:
            params["name"] = name.strip()
        if type:
            params["type"] = type.strip().upper()

        result = _make_request("GET", f"/zones/{zone_id}/dns_records", token, params=params)

        if "error" in result:
            return result

        # Extract records (could be dict with pagination info or direct list)
        records = result if isinstance(result, list) else result.get("records", [])

        normalized_records = [
            {
                "id": r.get("id"),
                "type": r.get("type"),
                "name": r.get("name"),
                "content": r.get("content"),
                "ttl": r.get("ttl"),
                "proxied": r.get("proxied"),
                "priority": r.get("priority"),
            }
            for r in records
        ]

        return {
            "records": normalized_records,
            "zone_id": zone_id,
            "page": page,
            "per_page": per_page,
            "total": len(normalized_records),
        }

    @mcp.tool("cloudflare_get_dns_record")
    def cloudflare_get_dns_record(zone_id: str, record_id: str) -> dict[str, Any]:
        """Get a specific DNS record by ID.

        Args:
            zone_id: Zone ID
            record_id: DNS record ID

        Returns:
            dict with record details or error
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        if not record_id or not isinstance(record_id, str):
            return {"error": "record_id must be a non-empty string"}

        result = _make_request("GET", f"/zones/{zone_id}/dns_records/{record_id}", token)

        if "error" in result:
            return result

        record = result if isinstance(result, dict) else {}

        return {
            "id": record.get("id"),
            "type": record.get("type"),
            "name": record.get("name"),
            "content": record.get("content"),
            "ttl": record.get("ttl"),
            "proxied": record.get("proxied"),
            "priority": record.get("priority"),
            "created_on": record.get("created_on"),
            "modified_on": record.get("modified_on"),
        }

    @mcp.tool("cloudflare_list_dns_record_scan")
    def cloudflare_list_dns_record_scan(zone_id: str) -> dict[str, Any]:
        """Scan for common DNS records that might be missing from Cloudflare.
        This is useful for importing existing domains.

        Args:
            zone_id: Zone ID

        Returns:
            list of records found during the scan
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("POST", f"/zones/{zone_id}/dns_records/scan", token)
        if "error" in result:
            return result

        return {"scan_result": result}

    @mcp.tool("cloudflare_get_dns_settings")
    def cloudflare_get_dns_settings(zone_id: str) -> dict[str, Any]:
        """Get DNS-specific settings for a zone (e.g. multi-provider, CNAME flattening).

        Args:
            zone_id: Zone ID

        Returns:
            DNS settings configuration
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/dns_settings", token)
        if "error" in result:
            return result

        return {"dns_settings": result}

    @mcp.tool("cloudflare_list_dns_analytics_report")
    def cloudflare_list_dns_analytics_report(zone_id: str, limit: int = 10) -> dict[str, Any]:
        """Get DNS query analytics and statistics (which types of queries are being made).

        Args:
            zone_id: Zone ID
            limit: Limit for results

        Returns:
            DNS analytics metrics
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Note: This endpoint often requires a specific analytics plan
        result = _make_request("GET", f"/zones/{zone_id}/dns_analytics/report", token)
        if "error" in result:
            return result

        return {"dns_analytics": result}

    @mcp.tool("cloudflare_check_domain_dns_health")
    def cloudflare_check_domain_dns_health(domain: str) -> dict[str, Any]:
        """Check DNS health and configuration for a domain.

        Performs a diagnostic check on a domain's DNS configuration,
        identifying missing records, proxy status issues, and common
        misconfiguration problems.

        Args:
            domain: Domain name to check (e.g., "example.com")

        Returns:
            dict with structured DNS health diagnosis including:
            - zone_found: bool indicating if zone exists
            - zone_status: current zone status
            - root_records: A/AAAA records for root domain
            - www_records: A/AAAA records for www subdomain
            - issues: list of detected DNS configuration issues
            - summary: human-readable summary
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_domain(domain)
        if validation_error:
            return validation_error

        domain = domain.lower().strip()

        # Find the zone for this domain
        zone_params = {"name": domain, "per_page": 1}
        zones_result = _make_request("GET", "/zones", token, params=zone_params)

        if "error" in zones_result:
            return {
                "domain": domain,
                "zone_found": False,
                "error": zones_result.get("error"),
                "issues": [
                    {"code": "ZONE_NOT_FOUND", "message": f"No zone found for domain {domain}"}
                ],
            }

        # Extract zone
        zones = zones_result if isinstance(zones_result, list) else []
        zone = zones[0] if zones else None

        if not zone or zone.get("name") != domain:
            return {
                "domain": domain,
                "zone_found": False,
                "issues": [
                    {"code": "ZONE_NOT_FOUND", "message": f"No zone found for domain {domain}"}
                ],
                "summary": f"Zone not found for {domain}.",
            }

        zone_id = zone.get("id")
        zone_status = zone.get("status")

        # Fetch DNS records
        records_params = {"per_page": 100}
        records_result = _make_request(
            "GET", f"/zones/{zone_id}/dns_records", token, params=records_params
        )

        if "error" in records_result:
            return {
                "domain": domain,
                "zone_found": True,
                "zone_status": zone_status,
                "error": records_result.get("error"),
                "issues": [{"code": "FETCH_ERROR", "message": "Failed to fetch DNS records"}],
            }

        # Extract records
        records = records_result if isinstance(records_result, list) else []

        # Categorize records
        root_records = [
            r for r in records if r.get("name") == domain and r.get("type") in ("A", "AAAA")
        ]
        www_records = [
            r
            for r in records
            if r.get("name") == f"www.{domain}" and r.get("type") in ("A", "AAAA")
        ]
        cname_records = [r for r in records if r.get("type") == "CNAME"]
        mx_records = [r for r in records if r.get("type") == "MX"]
        ns_records = [r for r in records if r.get("type") == "NS"]

        # Diagnose issues
        issues = []

        if zone_status != "active":
            issues.append(
                {
                    "code": "ZONE_INACTIVE",
                    "message": f"Zone status is {zone_status}, should be 'active'",
                }
            )

        if not root_records:
            issues.append(
                {
                    "code": "ROOT_MISSING",
                    "message": f"No A/AAAA records found for root domain {domain}",
                }
            )

        if not www_records and not cname_records:
            issues.append(
                {
                    "code": "WWW_MISSING",
                    "message": f"No www DNS record (A/AAAA or CNAME) found for {domain}",
                }
            )

        if not mx_records:
            issues.append(
                {
                    "code": "MX_MISSING",
                    "message": f"No MX records configured for {domain}",
                }
            )

        # Check for proxy mismatches (common issue with hosting provider integrations)
        for record in root_records + www_records:
            if record.get("proxied"):
                # Verify proxy targets are valid
                content = record.get("content", "")
                if not content:
                    issues.append(
                        {
                            "code": "PROXY_INVALID",
                            "message": f"Proxied record {record.get('name')} has no target",
                        }
                    )

        # Build summary
        record_count = len(records)
        summary = f"Zone is {zone_status}. Found {record_count} DNS records."

        if issues:
            issue_codes = [i.get("code") for i in issues]
            summary += f" Issues detected: {', '.join(issue_codes)}."
        else:
            summary += " No obvious DNS configuration issues detected."

        return {
            "domain": domain,
            "zone_found": True,
            "zone_id": zone_id,
            "zone_status": zone_status,
            "root_records": root_records,
            "www_records": www_records,
            "mx_records": mx_records,
            "ns_records": ns_records,
            "total_records": record_count,
            "issues": issues,
            "summary": summary,
        }

    @mcp.tool("cloudflare_create_dns_record")
    def cloudflare_create_dns_record(
        zone_id: str,
        type: str,
        name: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a new DNS record for a zone.

        Args:
            zone_id: Zone ID
            type: Record type (A, AAAA, CNAME, TXT, MX, etc.)
            name: DNS record name (e.g. 'sub' or 'example.com')
            content: Target content (IP, hostname, etc.)
            ttl: TTL value (1 for automatic)
            proxied: Whether to route through Cloudflare proxy
            priority: Priority for MX records (1-65535)

        Returns:
            created DNS record details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        data = {
            "type": type.upper(),
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }
        if priority is not None:
            data["priority"] = priority

        result = _make_request("POST", f"/zones/{zone_id}/dns_records", token, json_data=data)
        return {"created_record": result}

    @mcp.tool("cloudflare_update_dns_record")
    def cloudflare_update_dns_record(
        zone_id: str,
        record_id: str,
        type: str | None = None,
        name: str | None = None,
        content: str | None = None,
        ttl: int | None = None,
        proxied: bool | None = None,
    ) -> dict[str, Any]:
        """Update an existing DNS record.

        Args:
            zone_id: Zone ID
            record_id: DNS record ID
            type: Record type (A, AAAA, CNAME, etc.)
            name: DNS record name
            content: Target content
            ttl: TTL value
            proxied: Proxy status

        Returns:
            updated DNS record details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        data = {}
        if type:
            data["type"] = type.upper()
        if name:
            data["name"] = name
        if content:
            data["content"] = content
        if ttl:
            data["ttl"] = ttl
        if proxied is not None:
            data["proxied"] = proxied

        result = _make_request(
            "PATCH", f"/zones/{zone_id}/dns_records/{record_id}", token, json_data=data
        )
        return {"updated_record": result}

    @mcp.tool("cloudflare_delete_dns_record")
    def cloudflare_delete_dns_record(zone_id: str, record_id: str) -> dict[str, Any]:
        """Delete a single DNS record permanently.

        Args:
            zone_id: Zone ID
            record_id: Record ID to delete

        Returns:
            status of deletion
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}", token)
        return {"deleted": result}

    # --- ANALYTICS & MONITORING ---
    # Tools for traffic analysis, bandwidth, and visitor statistics

    @mcp.tool("cloudflare_get_zone_analytics")
    def cloudflare_get_zone_analytics(zone_id: str) -> dict[str, Any]:
        """Get analytics for a zone (last 24 hours).

        Args:
            zone_id: Zone ID

        Returns:
            dict with requests, bandwidth, and threats analytics
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Using the dashboard analytics and zone analytics endpoints
        result = _make_request("GET", f"/zones/{zone_id}/analytics/dashboard", token)
        if "error" in result:
            return result

        if isinstance(result, list):
            result = result[0] if result else {}

        totals = result.get("totals", {})
        return {
            "requests": totals.get("requests", {}).get("all"),
            "bandwidth_bytes": totals.get("bandwidth", {}).get("all"),
            "threats": totals.get("threats", {}).get("all"),
            "pageviews": totals.get("pageviews", {}).get("all"),
            "uniques": totals.get("uniques", {}).get("all"),
            "since": result.get("query", {}).get("since"),
            "until": result.get("query", {}).get("until"),
        }

    @mcp.tool("cloudflare_get_top_analytics")
    def cloudflare_get_top_analytics(zone_id: str) -> dict[str, Any]:
        """Get top paths and countries for a zone (last 24 hours).

        Args:
            zone_id: Zone ID

        Returns:
            dict with top paths and top countries
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/analytics/dashboard", token)
        if "error" in result:
            return result

        if isinstance(result, list):
            result = result[0] if result else {}

        # Extract top data from totals/requests
        req_data = result.get("totals", {}).get("requests", {})

        return {
            "top_countries": req_data.get("country", {}),
            "top_http_status": req_data.get("http_status", {}),
            "top_content_types": req_data.get("content_type", {}),
        }

    @mcp.tool("cloudflare_get_security_analytics")
    def cloudflare_get_security_analytics(zone_id: str) -> dict[str, Any]:
        """Get summarized security analytics (WAF, Bot, etc.).

        Args:
            zone_id: Zone ID

        Returns:
            Security analytics overview
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/security/analytics", token)
        if "error" in result:
            return result

        return {"security_analytics": result}

    @mcp.tool("cloudflare_get_cache_analytics")
    def cloudflare_get_cache_analytics(zone_id: str) -> dict[str, Any]:
        """Get cache performance analytics (Hit ratio, bandwidth saved).

        Args:
            zone_id: Zone ID

        Returns:
            Cache performance metrics
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/cache/analytics/dashboard", token)
        if "error" in result:
            return result

        return {"cache_analytics": result}

    @mcp.tool("cloudflare_get_performance_analytics")
    def cloudflare_get_performance_analytics(zone_id: str) -> dict[str, Any]:
        """Get detailed performance metrics (TTFB, loading times).

        Args:
            zone_id: Zone ID

        Returns:
            Performance analytics overview
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/analytics/dashboard", token)
        if "error" in result:
            return result

        if isinstance(result, list):
            result = result[0] if result else {}

        perf = result.get("totals", {}).get("performance", {})
        return {"performance_metrics": perf}

    @mcp.tool("cloudflare_get_http_analytics_report")
    def cloudflare_get_http_analytics_report(zone_id: str) -> dict[str, Any]:
        """Get detailed HTTP traffic reports (Errors, Status codes, Response times).

        Args:
            zone_id: Zone ID

        Returns:
            analytics summary for HTTP traffic
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Note: This often uses the GraphQL API internally, but we'll use the aggregated dashboard
        result = _make_request("GET", f"/zones/{zone_id}/analytics/dashboard", token)
        if "error" in result:
            return result

        if isinstance(result, list):
            result = result[0] if result else {}

        req = result.get("totals", {}).get("requests", {})
        return {
            "status_codes": req.get("http_status", {}),
            "content_types": req.get("content_type", {}),
            "threats": req.get("threats", {}),
        }

    # --- SECURITY & FIREWALL ---
    # Tools for monitoring security events, WAF, and firewall rules

    @mcp.tool("cloudflare_list_firewall_events")
    def cloudflare_list_firewall_events(zone_id: str, limit: int = 10) -> dict[str, Any]:
        """List recent firewall/security events for a zone.

        Args:
            zone_id: Zone ID
            limit: Number of events to return

        Returns:
            list of firewall events
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        params = {"per_page": min(limit, 50)}
        result = _make_request("GET", f"/zones/{zone_id}/firewall/events", token, params=params)

        if "error" in result:
            return result

        events = result if isinstance(result, list) else result.get("events", [])
        return {"events": events[:limit]}

    @mcp.tool("cloudflare_get_security_settings")
    def cloudflare_get_security_settings(zone_id: str) -> dict[str, Any]:
        """Get current security settings for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            dict with security level, SSL, and other settings
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Get multiple settings
        sec_level = _make_request("GET", f"/zones/{zone_id}/settings/security_level", token)
        ssl_setting = _make_request("GET", f"/zones/{zone_id}/settings/ssl", token)
        waf_setting = _make_request("GET", f"/zones/{zone_id}/settings/waf", token)

        return {
            "security_level": sec_level.get("value") if isinstance(sec_level, dict) else None,
            "ssl_mode": ssl_setting.get("value") if isinstance(ssl_setting, dict) else None,
            "waf_enabled": waf_setting.get("value") == "on"
            if isinstance(waf_setting, dict)
            else None,
        }

    @mcp.tool("cloudflare_list_page_rules")
    def cloudflare_list_page_rules(zone_id: str) -> dict[str, Any]:
        """List custom page rules (redirects, cache overrides) for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of page rules
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/pagerules", token)
        if "error" in result:
            return result

        rules = result if isinstance(result, list) else []
        return {
            "rules": [
                {
                    "id": r.get("id"),
                    "targets": r.get("targets"),
                    "actions": r.get("actions"),
                    "priority": r.get("priority"),
                    "status": r.get("status"),
                }
                for r in rules
            ]
        }

    @mcp.tool("cloudflare_list_waf_rulesets")
    def cloudflare_list_waf_rulesets(zone_id: str) -> dict[str, Any]:
        """List WAF rulesets for a zone (Modern WAF engine).

        Args:
            zone_id: Zone ID

        Returns:
            list of active and available WAF rulesets
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/rulesets", token)
        if "error" in result:
            return result

        return {"waf_rulesets": result}

    @mcp.tool("cloudflare_get_bot_management_settings")
    def cloudflare_get_bot_management_settings(zone_id: str) -> dict[str, Any]:
        """Get Bot Management configuration for a zone (Bot Fight Mode, etc.).

        Args:
            zone_id: Zone ID

        Returns:
            Bot management settings status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/bot_management", token)
        if "error" in result:
            return result

        return {"bot_management": result}

    @mcp.tool("cloudflare_list_managed_transforms")
    def cloudflare_list_managed_transforms(zone_id: str) -> dict[str, Any]:
        """List Managed Transforms (HTTP Header modifications) for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of managed transforms and their status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("GET", f"/zones/{zone_id}/managed_headers", token)
        if "error" in result:
            return result

        return {"managed_transforms": result}

    @mcp.tool("cloudflare_get_ddos_protection_settings")
    def cloudflare_get_ddos_protection_settings(zone_id: str) -> dict[str, Any]:
        """Get HTTP/L7 DDoS protection settings for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            DDoS protection configuration
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Note: DDoS settings are usually under rulesets with phase
        # 'http_ratelimit' or 'http_request_late_transform'. A general
        # config endpoint exists but may be limited.
        _make_request(
            "GET",
            f"/zones/{zone_id}/settings/automatic_https_rewrites",
            token,
        )

        return {"ddos_summary": "DDoS protection is on by default; see WAF rulesets for details."}

    @mcp.tool("cloudflare_create_firewall_rule")
    def cloudflare_create_firewall_rule(
        zone_id: str,
        action: str,
        expression: str,
        description: str | None = None,
        priority: int = 1,
    ) -> dict[str, Any]:
        """Create a custom firewall rule (IP/Country/Bot blocking).

        Args:
            zone_id: Zone ID
            action: Action to take ('block', 'challenge', 'js_challenge', 'allow', 'log')
            expression: Filter expression (e.g. 'ip.src eq 1.1.1.1' or 'cf.client.bot')
            description: Human-readable label
            priority: Execution priority

        Returns:
            created firewall rule details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        # Standard Cloudflare Firewall Rules API
        data = [
            {
                "action": action.lower(),
                "filter": {"expression": expression, "paused": False},
                "description": description or f"Rule created via MCP at {priority}",
                "priority": priority,
            }
        ]
        result = _make_request("POST", f"/zones/{zone_id}/firewall/rules", token, json_data=data)
        return {"created_rules": result}

    @mcp.tool("cloudflare_delete_firewall_rule")
    def cloudflare_delete_firewall_rule(zone_id: str, rule_id: str) -> dict[str, Any]:
        """Delete a firewall rule by ID.

        Args:
            zone_id: Zone ID
            rule_id: Rule ID to delete

        Returns:
            status message
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request("DELETE", f"/zones/{zone_id}/firewall/rules/{rule_id}", token)
        return {"deleted": result}

    # --- PERFORMANCE & SPEED ---
    # Tools for checking speed optimization and minification settings

    @mcp.tool("cloudflare_get_speed_settings")
    def cloudflare_get_speed_settings(zone_id: str) -> dict[str, Any]:
        """Check speed optimization settings (Minify, Brotli, etc.).

        Args:
            zone_id: Zone ID

        Returns:
            dict with speed settings status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        minify = _make_request("GET", f"/zones/{zone_id}/settings/minify", token)
        brotli = _make_request("GET", f"/zones/{zone_id}/settings/brotli", token)
        rocket = _make_request("GET", f"/zones/{zone_id}/settings/rocket_loader", token)

        return {
            "minify": minify.get("value") if isinstance(minify, dict) else None,
            "brotli": brotli.get("value") if isinstance(brotli, dict) else None,
            "rocket_loader": rocket.get("value") if isinstance(rocket, dict) else None,
        }

    @mcp.tool("cloudflare_get_cache_settings")
    def cloudflare_get_cache_settings(zone_id: str) -> dict[str, Any]:
        """Get cache settings for a zone (Browser cache TTL, Development mode, etc.).

        Args:
            zone_id: Zone ID

        Returns:
            dict with cache configuration status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        browser_cache = _make_request("GET", f"/zones/{zone_id}/settings/browser_cache_ttl", token)
        dev_mode = _make_request("GET", f"/zones/{zone_id}/settings/development_mode", token)
        cache_level = _make_request("GET", f"/zones/{zone_id}/settings/cache_level", token)

        return {
            "browser_cache_ttl": browser_cache.get("value")
            if isinstance(browser_cache, dict)
            else None,
            "development_mode": dev_mode.get("value") if isinstance(dev_mode, dict) else None,
            "cache_level": cache_level.get("value") if isinstance(cache_level, dict) else None,
        }

    @mcp.tool("cloudflare_get_http_config")
    def cloudflare_get_http_config(zone_id: str) -> dict[str, Any]:
        """Get HTTP protocol settings (HTTP/2, HTTP/3, 0-RTT) for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            dict with protocol configuration status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        h2 = _make_request("GET", f"/zones/{zone_id}/settings/http2", token)
        h3 = _make_request("GET", f"/zones/{zone_id}/settings/http3", token)
        zero_rtt = _make_request("GET", f"/zones/{zone_id}/settings/0rtt", token)

        return {
            "http2": h2.get("value") if isinstance(h2, dict) else None,
            "http3": h3.get("value") if isinstance(h3, dict) else None,
            "0rtt": zero_rtt.get("value") if isinstance(zero_rtt, dict) else None,
        }

    @mcp.tool("cloudflare_get_network_settings")
    def cloudflare_get_network_settings(zone_id: str) -> dict[str, Any]:
        """Get network-level performance settings (WebSockets, Onion Routing).

        Args:
            zone_id: Zone ID

        Returns:
            dict with network configuration status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        websockets = _make_request("GET", f"/zones/{zone_id}/settings/websockets", token)
        onion = _make_request("GET", f"/zones/{zone_id}/settings/onion_routing", token)
        ipv6 = _make_request("GET", f"/zones/{zone_id}/settings/ipv6", token)

        return {
            "websockets": websockets.get("value") if isinstance(websockets, dict) else None,
            "onion_routing": onion.get("value") if isinstance(onion, dict) else None,
            "ipv6": ipv6.get("value") if isinstance(ipv6, dict) else None,
        }

    @mcp.tool("cloudflare_purge_cache_all")
    def cloudflare_purge_cache_all(zone_id: str) -> dict[str, Any]:
        """Purge EVERYTHING from the Cloudflare cache for this zone.

        Args:
            zone_id: Zone ID

        Returns:
            status of purge operation
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request(
            "POST", f"/zones/{zone_id}/purge_cache", token, json_data={"purge_everything": True}
        )
        return {"purge_status": result}

    @mcp.tool("cloudflare_purge_cache_files")
    def cloudflare_purge_cache_files(zone_id: str, urls: list[str]) -> dict[str, Any]:
        """Purge specific URLs from the Cloudflare cache.

        Args:
            zone_id: Zone ID
            urls: List of full URLs to purge

        Returns:
            status of purge operation
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request(
            "POST", f"/zones/{zone_id}/purge_cache", token, json_data={"files": urls}
        )
        return {"purge_status": result}

    @mcp.tool("cloudflare_list_advanced_services")
    def cloudflare_list_advanced_services(zone_id: str) -> dict[str, Any]:
        """List Workers and Load Balancers for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            overview of advanced services
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        # Note: Workers and Load Balancers often require account-level access
        # but can be filtered by zone. Basic implementation here.
        workers = _make_request("GET", f"/zones/{zone_id}/workers/scripts", token)
        lb = _make_request("GET", f"/zones/{zone_id}/load_balancers", token)

        return {
            "workers_count": len(workers) if isinstance(workers, list) else 0,
            "load_balancers_count": len(lb) if isinstance(lb, list) else 0,
            "load_balancers": lb if isinstance(lb, list) else [],
        }

    # --- ACCOUNT LEVEL INSIGHTS ---
    # Tools for managing multiple accounts, billing, and system-wide audit logs

    @mcp.tool("cloudflare_list_accounts")
    def cloudflare_list_accounts(page: int = 1, per_page: int = 20) -> dict[str, Any]:
        """List all Cloudflare accounts the token has access to.

        Args:
            page: Page number
            per_page: Results per page (max 50)

        Returns:
            list of accounts (id, name, settings)
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        params = {"page": page, "per_page": min(per_page, 50)}
        result = _make_request("GET", "/accounts", token, params=params)

        if "error" in result:
            return result

        accounts = result if isinstance(result, list) else result.get("accounts", [])
        return {
            "accounts": [
                {"id": a.get("id"), "name": a.get("name"), "status": a.get("status")}
                for a in accounts
            ],
            "total": len(accounts),
        }

    @mcp.tool("cloudflare_get_account_details")
    def cloudflare_get_account_details(account_id: str) -> dict[str, Any]:
        """Get details for a specific Cloudflare account.

        Args:
            account_id: Account ID

        Returns:
            dict with account settings and configuration
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        result = _make_request("GET", f"/accounts/{account_id}", token)
        if "error" in result:
            return result

        if isinstance(result, list):
            result = result[0] if result else {}

        return {
            "id": result.get("id"),
            "name": result.get("name"),
            "settings": result.get("settings", {}),
            "created_on": result.get("created_on"),
        }

    @mcp.tool("cloudflare_list_account_members")
    def cloudflare_list_account_members(account_id: str) -> dict[str, Any]:
        """List all members/users in a specific account.

        Args:
            account_id: Account ID

        Returns:
            list of members and their roles
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        result = _make_request("GET", f"/accounts/{account_id}/members", token)
        return {"members": result}

    @mcp.tool("cloudflare_invite_account_member")
    def cloudflare_invite_account_member(
        account_id: str, email: str, roles: list[str]
    ) -> dict[str, Any]:
        """Invite a new member to an account with specific roles.

        Args:
            account_id: Account ID
            email: Email address of the person to invite
            roles: List of role IDs (e.g. ['05784...'] for Administrator)

        Returns:
            details of the invitation
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        data = {"email": email, "roles": roles}
        result = _make_request("POST", f"/accounts/{account_id}/members", token, json_data=data)
        return {"invitation": result}

    @mcp.tool("cloudflare_delete_account_member")
    def cloudflare_delete_account_member(account_id: str, member_id: str) -> dict[str, Any]:
        """Remove a member's access from an account.

        Args:
            account_id: Account ID
            member_id: Member ID to remove

        Returns:
            status of member removal
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        result = _make_request("DELETE", f"/accounts/{account_id}/members/{member_id}", token)
        return {"deleted": result}

    # --- ADVANCED SERVICES & ROUTING ---
    # Tools for Workers, Load Balancers, and SaaS hostnames configuration

    @mcp.tool("cloudflare_list_custom_hostnames")
    def cloudflare_list_custom_hostnames(zone_id: str) -> dict[str, Any]:
        """List custom hostnames (SSL for SaaS) for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of custom hostnames and their SSL status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        result = _make_request("GET", f"/zones/{zone_id}/custom_hostnames", token)
        if "error" in result:
            return result

        hostnames = result if isinstance(result, list) else result.get("custom_hostnames", [])
        return {"custom_hostnames": hostnames}

    @mcp.tool("cloudflare_list_audit_logs")
    def cloudflare_list_audit_logs(account_id: str, limit: int = 20) -> dict[str, Any]:
        """List recent audit logs for an account (who changed what).

        Args:
            account_id: Account ID
            limit: Number of records to return

        Returns:
            list of audit log entries
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        params = {"per_page": min(limit, 50)}
        result = _make_request("GET", f"/accounts/{account_id}/audit_logs", token, params=params)

        if "error" in result:
            return result

        logs = result if isinstance(result, list) else result.get("result", [])
        return {"audit_logs": logs[:limit]}

    @mcp.tool("cloudflare_list_firewall_rules")
    def cloudflare_list_firewall_rules(zone_id: str) -> dict[str, Any]:
        """List custom firewall rules for a zone.

        Args:
            zone_id: Zone ID

        Returns:
            list of firewall rules and their configurations
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        result = _make_request("GET", f"/zones/{zone_id}/firewall/rules", token)
        if "error" in result:
            return result

        rules = result if isinstance(result, list) else []
        return {"firewall_rules": rules}

    @mcp.tool("cloudflare_list_access_applications")
    def cloudflare_list_access_applications(account_id: str) -> dict[str, Any]:
        """List Cloudflare Access (Zero Trust) applications for an account.

        Args:
            account_id: Account ID

        Returns:
            list of protected applications
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token

        result = _make_request("GET", f"/accounts/{account_id}/access/apps", token)
        if "error" in result:
            return result

        apps = result if isinstance(result, list) else []
        return {"access_applications": apps}

    @mcp.tool("cloudflare_list_r2_buckets")
    def cloudflare_list_r2_buckets(account_id: str) -> dict[str, Any]:
        """List all R2 storage buckets for an account.

        Args:
            account_id: Account ID

        Returns:
            list of R2 buckets and their details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        result = _make_request("GET", f"/accounts/{account_id}/r2/buckets", token)
        return {"r2_buckets": result}

    @mcp.tool("cloudflare_list_pages_projects")
    def cloudflare_list_pages_projects(account_id: str) -> dict[str, Any]:
        """List all Cloudflare Pages projects for an account.

        Args:
            account_id: Account ID

        Returns:
            list of Pages projects and their statuses
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        result = _make_request("GET", f"/accounts/{account_id}/pages/projects", token)
        return {"pages_projects": result}

    @mcp.tool("cloudflare_create_access_policy")
    def cloudflare_create_access_policy(
        account_id: str,
        application_id: str,
        name: str,
        decision: str,
        include: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a new Zero Trust Access policy.

        Args:
            account_id: Account ID
            application_id: Application ID to protect
            name: Policy name
            decision: Policy decision ('allow', 'deny', 'bypass')
            include: List of criteria (e.g. [{"email": {"email": "user@example.com"}}])

        Returns:
            created policy details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        data = {"name": name, "decision": decision, "include": include}
        result = _make_request(
            "POST",
            f"/accounts/{account_id}/access/apps/{application_id}/policies",
            token,
            json_data=data,
        )
        return {"policy": result}

    @mcp.tool("cloudflare_create_worker_route")
    def cloudflare_create_worker_route(
        zone_id: str, pattern: str, script_name: str
    ) -> dict[str, Any]:
        """Activate a Worker script on a specific URL pattern.

        Args:
            zone_id: Zone ID
            pattern: URL pattern (e.g. 'api.example.com/*')
            script_name: Name of the worker script already uploaded

        Returns:
            created route details
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        data = {"pattern": pattern, "script": script_name}
        result = _make_request("POST", f"/zones/{zone_id}/workers/routes", token, json_data=data)
        return {"route": result}

    @mcp.tool("cloudflare_set_ssl_mode")
    def cloudflare_set_ssl_mode(zone_id: str, mode: str) -> dict[str, Any]:
        """Directly set the SSL mode for a zone.

        Args:
            zone_id: Zone ID
            mode: SSL mode ('off', 'flexible', 'full', 'strict')

        Returns:
            updated SSL setting status
        """
        token = _get_token(credentials)
        if isinstance(token, dict):
            return token
        validation_error = _validate_zone_id(zone_id)
        if validation_error:
            return validation_error

        result = _make_request(
            "PATCH", f"/zones/{zone_id}/settings/ssl", token, json_data={"value": mode}
        )
        return {"ssl_update": result}

    return None
