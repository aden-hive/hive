import logging
import json
from typing import Any, Optional, Union
import httpx
from fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

class TwilioClient:
    """Client for interacting with Twilio API using httpx."""
    
    BASE_URL = "https://api.twilio.com/2010-04-01/Accounts"
    LOOKUP_URL = "https://lookups.twilio.com/v2/PhoneNumbers"

    def __init__(self, account_sid: str, auth_token: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.auth = (account_sid, auth_token)

    def _request(self, method: str, url: str, **kwargs) -> dict:
        """Handle API requests with basic auth and error management."""
        with httpx.Client(auth=self.auth) as client:
            try:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                try:
                    error_data = e.response.json()
                    message = error_data.get("message", e.response.text)
                except Exception:
                    message = e.response.text
                
                logger.error(f"Twilio API Error ({status_code}): {message}")
                raise ValueError(f"Twilio Error: {message}")
            except Exception as e:
                logger.error(f"Twilio Request Error: {str(e)}")
                raise e

    def send_message(self, to: str, body: str, from_number: str, media_url: Optional[str] = None) -> dict:
        """Send an SMS or WhatsApp message."""
        url = f"{self.BASE_URL}/{self.account_sid}/Messages.json"
        data = {
            "To": to,
            "From": from_number,
            "Body": body
        }
        if media_url:
            data["MediaUrl"] = media_url
            
        return self._request("POST", url, data=data)

    def fetch_history(self, limit: int = 50, to: Optional[str] = None) -> list[dict]:
        """Fetch message history logs."""
        url = f"{self.BASE_URL}/{self.account_sid}/Messages.json"
        params = {"PageSize": limit}
        if to:
            params["To"] = to
            
        response = self._request("GET", url, params=params)
        return response.get("messages", [])

    def validate_number(self, phone_number: str) -> dict:
        """Validate phone number using Twilio Lookup API."""
        url = f"{self.LOOKUP_URL}/{phone_number}"
        params = {"Fields": "line_type_intelligence"}
        return self._request("GET", url, params=params)

def register_tools(mcp: FastMCP, credentials=None):
    """Register Twilio tools with the MCP server."""

    def get_client() -> TwilioClient:
        if not credentials:
            raise ValueError("Credential manager not provided.")
        
        credentials.validate_for_tools(["send_sms"])
        sid = credentials.get("twilio_account_sid")
        token = credentials.get("twilio_auth_token")
        
        if not sid or not token:
            raise ValueError("Twilio credentials (SID or Token) missing.")
            
        return TwilioClient(sid, token)

    @mcp.tool()
    def send_sms(to: str, body: str, media_url: Optional[str] = None, ctx: Context = None) -> str:
        """
        Send a standard SMS or MMS text message.
        
        Args:
            to: Recipient phone number (E.164 format, e.g., +1234567890)
            body: Message content
            media_url: Optional URL for image or media (MMS)
        """
        try:
            client = get_client()
            from_number = credentials.get("twilio_from_number")
            if not from_number:
                return "Error: TWILIO_FROM_NUMBER credential missing."
            
            result = client.send_message(to, body, from_number, media_url)
            return json.dumps({
                "MessageSID": result.get("sid"),
                "Status": result.get("status"),
                "Direction": result.get("direction")
            }, indent=2)
        except Exception as e:
            return f"Error sending SMS: {str(e)}"

    @mcp.tool()
    def send_whatsapp(to: str, body: str, media_url: Optional[str] = None, ctx: Context = None) -> str:
        """
        Send a WhatsApp message.
        
        Args:
            to: Recipient WhatsApp number (prefixed with whatsapp:, e.g., whatsapp:+1234567890)
            body: Message content
            media_url: Optional URL for media
        """
        try:
            client = get_client()
            from_number = credentials.get("twilio_from_number")
            if not from_number:
                return "Error: TWILIO_FROM_NUMBER credential missing."
            
            # Ensure whatsapp: prefix
            if not to.startswith("whatsapp:"):
                to = f"whatsapp:{to}"
            if not from_number.startswith("whatsapp:"):
                from_number = f"whatsapp:{from_number}"
                
            result = client.send_message(to, body, from_number, media_url)
            return json.dumps({
                "MessageSID": result.get("sid"),
                "Status": result.get("status")
            }, indent=2)
        except Exception as e:
            return f"Error sending WhatsApp: {str(e)}"

    @mcp.tool()
    def fetch_history(limit: int = 20, to: Optional[str] = None, ctx: Context = None) -> str:
        """
        Retrieve recent message logs.
        
        Args:
            limit: Maximum number of records to retrieve (default 20)
            to: Optional filter by recipient number
        """
        try:
            client = get_client()
            history = client.fetch_history(limit, to)
            # Simplify response for agent consumption
            formatted = []
            for msg in history:
                formatted.append({
                    "sid": msg.get("sid"),
                    "from": msg.get("from"),
                    "to": msg.get("to"),
                    "body": msg.get("body"),
                    "status": msg.get("status"),
                    "direction": msg.get("direction"),
                    "date_sent": msg.get("date_sent")
                })
            return json.dumps(formatted, indent=2)
        except Exception as e:
            return f"Error fetching history: {str(e)}"

    @mcp.tool()
    def validate_number(phone_number: str, ctx: Context = None) -> str:
        """
        Validate and lookup information about a phone number.
        
        Args:
            phone_number: The number to validate (E.164 format)
        """
        try:
            client = get_client()
            info = client.validate_number(phone_number)
            return json.dumps({
                "formatted_number": info.get("phone_number"),
                "valid": info.get("valid", False),
                "carrier": info.get("line_type_intelligence", {}).get("carrier_name"),
                "type": info.get("line_type_intelligence", {}).get("type")
            }, indent=2)
        except Exception as e:
            return f"Error validating number: {str(e)}"
