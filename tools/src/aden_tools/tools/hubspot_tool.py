"""
HubSpot Integration Tools - CRM and Webhook management.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

from aden_tools.credentials import CredentialManager

logger = logging.getLogger(__name__)

def register_tools(mcp: FastMCP, credentials: Optional[CredentialManager] = None):
    """
    Register HubSpot tools with the FastMCP server.
    """
    
    @mcp.tool()
    async def hubspot_health_check() -> str:
        """
        Verify HubSpot credential validity by fetching a single contact.
        
        Returns:
            Status message indicating success or failure.
        """
        creds = credentials or CredentialManager()
        token = creds.get("hubspot")
        
        if not token:
            return "❌ Missing HUBSPOT_ACCESS_TOKEN"
            
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    "https://api.hubapi.com/crm/v3/objects/contacts",
                    params={"limit": 1},
                    headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                return "✅ HubSpot connection active. Successfully fetched contact list."
            except Exception as e:
                return f"❌ HubSpot health check failed: {str(e)}"

    @mcp.tool()
    async def hubspot_webhook_verify(
        request_body: str,
        signature: str,
        timestamp: str,
    ) -> bool:
        """
        Verify an incoming HubSpot webhook signature (V3).
        
        Args:
            request_body: Raw UTF-8 encoded request body.
            signature: The 'X-HubSpot-Signature-v3' header value.
            timestamp: The 'X-HubSpot-Request-Timestamp' header value.
            
        Returns:
            True if signature is valid, False otherwise.
        """
        creds = credentials or CredentialManager()
        secret = creds.get("hubspot_webhook_secret")
        
        if not secret:
            logger.error("Missing HUBSPOT_WEBHOOK_SIGNING_SECRET")
            return False
            
        # Verify timestamp to prevent replay attacks (5 minute window)
        try:
            ts = int(timestamp)
            if abs(time.time() - (ts / 1000)) > 300:
                logger.warning("HubSpot webhook timestamp out of window")
                return False
        except ValueError:
            return False

        # Construct source string: secret + request_body + timestamp
        # Note: HubSpot V3 uses HMAC-SHA256
        source = request_body + timestamp
        
        computed_signature = hmac.new(
            secret.encode("utf-8"),
            source.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        # HubSpot might send signature in base64 or hex depending on version, 
        # but V3 documentation usually refers to hex for the raw HMAC result.
        # Actually, V3 signature is base64 encoded.
        import base64
        computed_base64 = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                source.encode("utf-8"),
                hashlib.sha256
            ).digest()
        ).decode("utf-8")
        
        return hmac.compare_digest(computed_base64, signature)

    @mcp.tool()
    async def hubspot_list_webhook_subscriptions(app_id: int) -> dict[str, Any]:
        """
        List all webhook subscriptions for a specific HubSpot app.
        
        Args:
            app_id: The ID of the HubSpot app.
            
        Returns:
            List of subscriptions.
        """
        creds = credentials or CredentialManager()
        token = creds.get("hubspot")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.hubapi.com/webhooks/v1/{app_id}/subscriptions",
                headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def hubspot_register_webhook_subscription(
        app_id: int,
        event_type: str,
        property_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Register a new webhook subscription in HubSpot.
        
        Args:
            app_id: The ID of the HubSpot app.
            event_type: The type of event (e.g., 'contact.creation', 'deal.propertyChange').
            property_name: The CRM property to monitor (if applicable).
            
        Returns:
            The created subscription object.
        """
        creds = credentials or CredentialManager()
        token = creds.get("hubspot")
        
        payload = {
            "eventType": event_type,
            "active": True
        }
        if property_name:
            payload["propertyName"] = property_name
            
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.hubapi.com/webhooks/v1/{app_id}/subscriptions",
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
            response.raise_for_status()
            return response.json()
