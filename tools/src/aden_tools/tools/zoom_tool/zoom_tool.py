"""
Zoom Tool
Allows agents to manage meetings via Zoom Server-to-Server OAuth.
"""
import os
import requests
import base64
from typing import Dict, Any, Optional

BASE_URL = "https://api.zoom.us/v2"

def _get_access_token(account_id: str, client_id: str, client_secret: str) -> str:
    """Helper to get Server-to-Server OAuth token."""
    url = "https://zoom.us/oauth/token"
    
    # Create Basic Auth header
    raw_creds = f"{client_id}:{client_secret}"
    b64_creds = base64.b64encode(raw_creds.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_creds}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    params = {
        "grant_type": "account_credentials",
        "account_id": account_id
    }
    
    resp = requests.post(url, headers=headers, data=params)
    resp.raise_for_status()
    return resp.json()["access_token"]

def _get_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """
    Constructs authorization headers.
    We expect credentials in environment variables since we need 3 keys.
    """
    # Load credentials from env if not passed explicitly
    acc_id = os.environ.get("ZOOM_ACCOUNT_ID")
    cli_id = os.environ.get("ZOOM_CLIENT_ID")
    cli_sec = os.environ.get("ZOOM_CLIENT_SECRET")
    
    if not all([acc_id, cli_id, cli_sec]):
        raise ValueError("Missing Zoom credentials (ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET)")

    token = _get_access_token(acc_id, cli_id, cli_sec)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def create_meeting(
    topic: str,
    start_time: str,
    duration: int,
    agenda: str = "",
    host_email: str = "me"
) -> Dict[str, Any]:
    """
    Creates a scheduled meeting.
    
    Args:
        topic (str): Meeting title.
        start_time (str): Start time in ISO format (e.g., "2023-10-30T10:00:00Z").
        duration (int): Duration in minutes.
        agenda (str): Description of the meeting.
        host_email (str): Email of the host (or 'me' if using user-level app).
                          For Server-to-Server, providing a specific email is recommended.
    
    Returns:
        Dict: Meeting join details.
    """
    try:
        headers = _get_headers()
        # "me" doesn't work well with Server-to-Server OAuth unless asking for the owner,
        # so we default to 'me' but allow agents to specify an email.
        url = f"{BASE_URL}/users/{host_email}/meetings"
        
        payload = {
            "topic": topic,
            "type": 2, # Scheduled meeting
            "start_time": start_time,
            "duration": duration,
            "agenda": agenda,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": True
            }
        }
        
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "result": "success",
            "join_url": data.get("join_url"),
            "start_url": data.get("start_url"),
            "password": data.get("password"),
            "id": data.get("id")
        }
    except Exception as e:
        return {"error": str(e)}

def list_meetings(limit: int = 5, host_email: str = "me") -> Dict[str, Any]:
    """
    Lists upcoming meetings for a user.
    """
    try:
        headers = _get_headers()
        url = f"{BASE_URL}/users/{host_email}/meetings"
        params = {"page_size": limit, "type": "upcoming"}
        
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        meetings = []
        for m in data.get("meetings", []):
            meetings.append({
                "id": m.get("id"),
                "topic": m.get("topic"),
                "start_time": m.get("start_time"),
                "join_url": m.get("join_url")
            })
            
        return {"result": "success", "meetings": meetings}
    except Exception as e:
        return {"error": str(e)}

def get_meeting_details(meeting_id: str) -> Dict[str, Any]:
    """
    Retrieves details for a specific meeting ID.
    """
    try:
        headers = _get_headers()
        url = f"{BASE_URL}/meetings/{meeting_id}"
        
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "result": "success",
            "topic": data.get("topic"),
            "status": data.get("status"),
            "start_time": data.get("start_time"),
            "duration": data.get("duration"),
            "join_url": data.get("join_url")
        }
    except Exception as e:
        return {"error": str(e)}