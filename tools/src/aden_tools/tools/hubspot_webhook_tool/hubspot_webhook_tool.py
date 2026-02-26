from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """
    Register HubSpot webhook tools.

    These tools do NOT require HubSpot credentials because
    webhook verification only depends on the signing secret.
    """

    @mcp.tool()
    def hubspot_webhook_verify(
        body: str,
        headers: dict[str, str],
        signing_secret: str,
    ) -> dict[str, bool]:
        """
        Verify HubSpot webhook signature using HMAC SHA256.
        """

        if not isinstance(headers, dict):
            return {"valid": False}

        signature = headers.get("X-HubSpot-Signature-256")
        if not signature:
            return {"valid": False}

        computed_hash = hmac.new(
            signing_secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        expected_signature = f"sha256={computed_hash}"

        is_valid = hmac.compare_digest(expected_signature, signature)

        return {"valid": is_valid}

    @mcp.tool()
    def hubspot_webhook_receive(event: dict[str, Any]) -> dict[str, Any]:
        """
        Parse and structure a HubSpot webhook event payload.
        """

        if not isinstance(event, dict):
            return {"error": "Invalid payload"}

        return {
            "event_type": event.get("subscriptionType"),
            "object_id": event.get("objectId"),
            "occurred_at": event.get("occurredAt"),
            "raw": event,
        }
