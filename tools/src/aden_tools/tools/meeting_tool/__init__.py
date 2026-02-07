from fastmcp import FastMCP
from .zoom_client import ZoomClient
from ...credentials import CredentialManager

def _get_client(credentials=None) -> ZoomClient:
    creds = credentials or CredentialManager()
    return ZoomClient(
        account_id=creds.get("ZOOM_ACCOUNT_ID"),
        client_id=creds.get("ZOOM_CLIENT_ID"),
        client_secret=creds.get("ZOOM_CLIENT_SECRET")
    )

# --- Tool Wrappers ---

def create_meeting(topic: str, start_time: str, duration_minutes: int, agenda: str = ""):
    """
    Schedule a Zoom meeting.
    start_time format: '2024-12-31T10:00:00'
    """
    client = _get_client()
    host = CredentialManager().get("ZOOM_USER_EMAIL", "me")
    return client.create_meeting(topic, start_time, duration_minutes, agenda, host)

def list_upcoming_meetings(limit: int = 5):
    """List upcoming scheduled meetings."""
    client = _get_client()
    host = CredentialManager().get("ZOOM_USER_EMAIL", "me")
    return client.list_meetings(host, limit=limit)

def get_meeting_details(meeting_id: str):
    """Get status, start time, and join URL for a specific meeting."""
    client = _get_client()
    return client.get_meeting_details(meeting_id)

def update_meeting(meeting_id: str, topic: str = None, start_time: str = None, duration: int = None):
    """
    Update an existing meeting.
    Only provide fields you want to change.
    """
    updates = {}
    if topic: updates['topic'] = topic
    if start_time: updates['start_time'] = start_time
    if duration: updates['duration'] = duration
    
    client = _get_client()
    return client.update_meeting(meeting_id, **updates)

def delete_meeting(meeting_id: str):
    """Cancel and delete a meeting."""
    client = _get_client()
    return client.delete_meeting(meeting_id)

def get_meeting_transcript(meeting_id: str):
    """
    Retrieve the full text transcript of a past meeting.
    Useful for summarization and memory.
    """
    client = _get_client()
    return client.get_transcript_text(meeting_id)

def register_tools(mcp: FastMCP):
    mcp.tool()(create_meeting)
    mcp.tool()(list_upcoming_meetings)
    mcp.tool()(get_meeting_details)
    mcp.tool()(update_meeting)
    mcp.tool()(delete_meeting)
    mcp.tool()(get_meeting_transcript)

__all__ = [
    "register_tools", 
    "create_meeting", 
    "list_upcoming_meetings", 
    "get_meeting_details",
    "update_meeting",
    "delete_meeting",
    "get_meeting_transcript"
]