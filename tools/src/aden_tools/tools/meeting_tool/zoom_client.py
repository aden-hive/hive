"""
Zoom Client for Aden Hive.

A robust, server-to-server OAuth enabled client for the Zoom API.
Handles rate limiting, pagination, token rotation, and complex UUID encoding.

Capabilities:
- Scheduling & Lifecycle (Create, Update, Delete)
- Intelligence (Transcripts, Recordings)
- Operations (Participants, Registrants)
"""

import base64
import logging
import time
import urllib.parse
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Union

import requests

# Configure module-level logger
logger = logging.getLogger(__name__)


class ZoomMeetingType(Enum):
    INSTANT = 1
    SCHEDULED = 2
    RECURRING_NO_FIXED_TIME = 3
    RECURRING_FIXED_TIME = 8


class ZoomError(Exception):
    """Base exception for Zoom Client errors."""
    pass


class ZoomAuthError(ZoomError):
    """Failed to authenticate or refresh token."""
    pass


class ZoomRateLimitError(ZoomError):
    """API rate limit exceeded (429)."""
    pass


class ZoomResourceNotFoundError(ZoomError):
    """Resource not found (404)."""
    pass


class ZoomAPIError(ZoomError):
    """Generic API error with status code and message."""
    def __init__(self, message: str, status_code: int, response_body: Any = None):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.response_body = response_body


class ZoomClient:
    """
    Production-ready Zoom API Client using Server-to-Server OAuth.
    """

    BASE_URL = "https://api.zoom.us/v2"
    AUTH_URL = "https://zoom.us/oauth/token"
    
    # Default timeouts
    CONNECT_TIMEOUT = 5.0
    READ_TIMEOUT = 30.0

    def __init__(
        self, 
        account_id: str, 
        client_id: str, 
        client_secret: str, 
        max_retries: int = 3
    ):
        """
        Initialize the Zoom Client.

        Args:
            account_id: Zoom Account ID (Server-to-Server OAuth).
            client_id: Zoom App Client ID.
            client_secret: Zoom App Client Secret.
            max_retries: Number of times to retry on 429 or 5xx errors.
        """
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.max_retries = max_retries
        
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._session = requests.Session()

    # =========================================================================
    # AUTHENTICATION & CORE REQUEST LOGIC
    # =========================================================================

    def _get_token(self) -> str:
        """
        Retrieves or rotates the OAuth access token.
        
        Returns:
            Valid access token string.
            
        Raises:
            ZoomAuthError: If authentication fails.
        """
        # Return cached token if valid (with 60s buffer)
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        logger.debug("Refreshing Zoom OAuth token...")

        auth_string = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        params = {
            "grant_type": "account_credentials",
            "account_id": self.account_id
        }

        try:
            response = self._session.post(
                self.AUTH_URL, 
                params=params, 
                headers=headers,
                timeout=self.CONNECT_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data["access_token"]
            # Set expiration based on 'expires_in' (usually 3600 seconds)
            self._token_expires_at = time.time() + data.get("expires_in", 3599)
            
            logger.info("Successfully refreshed Zoom OAuth token.")
            return self._access_token

        except requests.exceptions.RequestException as e:
            msg = f"Failed to authenticate with Zoom: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                msg += f" Body: {e.response.text}"
            logger.error(msg)
            raise ZoomAuthError(msg) from e

    def _request(
        self, 
        method: str, 
        endpoint: str, 
        params: Dict[str, Any] = None, 
        json: Dict[str, Any] = None,
        stream: bool = False
    ) -> Union[Dict[str, Any], requests.Response]:
        """
        Centralized request handler with retry logic and error mapping.
        """
        url = f"{self.BASE_URL}{endpoint}"
        retry_count = 0

        while retry_count <= self.max_retries:
            try:
                token = self._get_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "Aden-Hive-Agent/1.0"
                }

                logger.debug(f"Zoom API Request: {method} {url}")
                
                response = self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT),
                    stream=stream
                )

                # --- Handle Success ---
                if response.status_code == 204:
                    return {"status": "success"}  # No content success
                
                if 200 <= response.status_code < 300:
                    return response if stream else response.json()

                # --- Handle Rate Limits (429) ---
                if response.status_code == 429:
                    retry_count += 1
                    # Zoom sends 'Retry-After' in headers (seconds)
                    # If missing, default to exponential backoff
                    retry_after = int(response.headers.get("Retry-After", 2 ** retry_count))
                    
                    if retry_count > self.max_retries:
                        raise ZoomRateLimitError(f"Max retries exceeded. Rate limited for {retry_after}s")
                    
                    logger.warning(f"Rate limited. Sleeping for {retry_after}s (Attempt {retry_count}/{self.max_retries})")
                    time.sleep(retry_after)
                    continue

                # --- Handle Errors ---
                if response.status_code == 404:
                    raise ZoomResourceNotFoundError(f"Resource not found: {url}")
                
                if response.status_code == 401:
                    # Token might be invalid, force expire and retry once
                    self._access_token = None
                    if retry_count == 0:
                        retry_count += 1
                        continue
                    raise ZoomAuthError("Unauthorized. Token invalid.")

                # Generic API Error
                try:
                    error_body = response.json()
                    err_msg = error_body.get("message") or error_body.get("error")
                except:
                    error_body = response.text
                    err_msg = "Unknown error"

                raise ZoomAPIError(
                    f"Zoom API Error {response.status_code}: {err_msg}",
                    status_code=response.status_code,
                    response_body=error_body
                )

            except requests.exceptions.ConnectionError:
                retry_count += 1
                if retry_count > self.max_retries:
                    raise
                time.sleep(1)

    def _encode_uuid(self, uuid: str) -> str:
        """
        Zoom requires UUIDs containing '/' or '+' to be double URL-encoded.
        Example: "uv0/123==" -> "uv0%252F123%253D%253D"
        """
        if uuid.startswith("/") or "//" in uuid or "+" in uuid:
            return urllib.parse.quote(urllib.parse.quote(uuid, safe=''), safe='')
        return uuid

    def _paginate(self, endpoint: str, key: str, params: Dict[str, Any] = None) -> Generator[Dict, None, None]:
        """
        Generator to fetch all pages of a resource automatically.
        
        Args:
            endpoint: API endpoint.
            key: The JSON key containing the list of items (e.g., 'meetings', 'participants').
            params: Initial query parameters.
        """
        if params is None:
            params = {}
        
        params["page_size"] = 300  # Maximize page size for efficiency
        next_page_token = ""

        while True:
            if next_page_token:
                params["next_page_token"] = next_page_token
            
            data = self._request("GET", endpoint, params=params)
            items = data.get(key, [])
            
            for item in items:
                yield item
            
            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break

    # =========================================================================
    # MEETING SCHEDULING & LIFECYCLE
    # =========================================================================

    def create_meeting(
        self, 
        topic: str, 
        start_time: str, 
        duration_min: int, 
        agenda: str = "", 
        host_email: str = "me",
        auto_record: str = "cloud"
    ) -> Dict[str, Any]:
        """
        Create a scheduled meeting.

        Args:
            topic: Meeting title.
            start_time: ISO8601 format (e.g. '2024-01-01T10:00:00').
            duration_min: Duration in minutes.
            host_email: Email of the user creating the meeting (or 'me').
            auto_record: 'local', 'cloud', or 'none'.
        """
        user_id = host_email if host_email != "me" else "me"
        
        payload = {
            "topic": topic,
            "type": ZoomMeetingType.SCHEDULED.value,
            "start_time": start_time,
            "duration": duration_min,
            "agenda": agenda,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": True,
                "mute_upon_entry": True,
                "watermark": False,
                "audio": "both",
                "auto_recording": auto_record
            }
        }
        return self._request("POST", f"/users/{user_id}/meetings", json=payload)

    def get_meeting_details(self, meeting_id: str) -> Dict[str, Any]:
        """Retrieve details of a scheduled or past meeting."""
        safe_id = self._encode_uuid(meeting_id)
        return self._request("GET", f"/meetings/{safe_id}")

    def update_meeting(self, meeting_id: str, **updates) -> Dict[str, Any]:
        """
        Update specific fields of a meeting.
        
        Args:
            meeting_id: ID of meeting to update.
            **updates: Fields to update (topic, start_time, duration, etc.)
        """
        safe_id = self._encode_uuid(meeting_id)
        # Filter out None values
        payload = {k: v for k, v in updates.items() if v is not None}
        return self._request("PATCH", f"/meetings/{safe_id}", json=payload)

    def delete_meeting(self, meeting_id: str, notify_host: bool = False) -> Dict[str, Any]:
        """Delete a meeting."""
        safe_id = self._encode_uuid(meeting_id)
        params = {"schedule_for_reminder": str(notify_host).lower()}
        return self._request("DELETE", f"/meetings/{safe_id}", params=params)

    def list_meetings(
        self, 
        host_email: str = "me", 
        type: str = "scheduled", 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List meetings for a user.
        
        Args:
            type: 'scheduled', 'live', or 'upcoming'.
            limit: Max results to return.
        """
        user_id = host_email if host_email != "me" else "me"
        endpoint = f"/users/{user_id}/meetings"
        
        # Using the paginator to fetch up to 'limit'
        results = []
        generator = self._paginate(endpoint, "meetings", params={"type": type})
        
        try:
            for _ in range(limit):
                results.append(next(generator))
        except StopIteration:
            pass
            
        return results

    # =========================================================================
    # MEETING INTELLIGENCE (TRANSCRIPTS & RECORDINGS)
    # =========================================================================

    def get_meeting_recordings(self, meeting_id: str) -> Dict[str, Any]:
        """
        Get all cloud recordings for a meeting.
        """
        safe_id = self._encode_uuid(meeting_id)
        return self._request("GET", f"/meetings/{safe_id}/recordings")

    def get_transcript_url(self, meeting_id: str) -> Optional[str]:
        """
        Finds the download URL for the transcript file.
        """
        try:
            data = self.get_meeting_recordings(meeting_id)
        except ZoomResourceNotFoundError:
            logger.warning(f"No recordings found for meeting {meeting_id}")
            return None

        files = data.get("recording_files", [])
        
        # Look for the transcript file type
        transcript = next((f for f in files if f.get("file_type") == "TRANSCRIPT"), None)
        
        if transcript:
            return transcript.get("download_url")
        return None

    def get_transcript_text(self, meeting_id: str) -> str:
        """
        Fetches and downloads the full transcript text content.
        This enables the 'Memory' capability of the agent.
        """
        download_url = self.get_transcript_url(meeting_id)
        
        if not download_url:
            return "Transcript not available. Ensure 'Cloud Recording' was enabled."

        # Fetching the file content requires the OAuth token in the header
        token = self._get_token()
        try:
            # We use a direct requests call here because this is a file download, 
            # not a standard API JSON response
            response = requests.get(
                download_url, 
                headers={"Authorization": f"Bearer {token}"},
                timeout=60
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to download transcript: {e}")
            return f"Error downloading transcript: {str(e)}"

    # =========================================================================
    # PARTICIPANTS & REGISTRANTS
    # =========================================================================

    def list_past_participants(self, meeting_id: str) -> List[Dict[str, Any]]:
        """
        Get list of participants from a past meeting. 
        Critical for attendance tracking.
        """
        safe_id = self._encode_uuid(meeting_id)
        endpoint = f"/report/meetings/{safe_id}/participants"
        
        # This endpoint is paginated
        participants = list(self._paginate(endpoint, "participants"))
        return participants

    def add_registrant(
        self, 
        meeting_id: str, 
        email: str, 
        first_name: str, 
        last_name: str = ""
    ) -> Dict[str, Any]:
        """Register a user for a meeting (if registration is required)."""
        safe_id = self._encode_uuid(meeting_id)
        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name
        }
        return self._request("POST", f"/meetings/{safe_id}/registrants", json=payload)

    def list_registrants(self, meeting_id: str, status: str = "approved") -> List[Dict[str, Any]]:
        """List people registered for the meeting."""
        safe_id = self._encode_uuid(meeting_id)
        endpoint = f"/meetings/{safe_id}/registrants"
        
        return list(self._paginate(endpoint, "registrants", params={"status": status}))

    # =========================================================================
    # USER MANAGEMENT
    # =========================================================================

    def get_me(self) -> Dict[str, Any]:
        """Get current bot/user info."""
        return self._request("GET", "/users/me")

    def list_users(self, status: str = "active") -> List[Dict[str, Any]]:
        """List all users in the account."""
        return list(self._paginate("/users", "users", params={"status": status}))