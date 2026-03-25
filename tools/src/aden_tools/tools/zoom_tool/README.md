# Zoom Tool

Meeting management, recordings, and user info via the Zoom REST API.

## Supported Actions

- **zoom_get_user** – Get user profile (defaults to authenticated user)
- **zoom_list_meetings** / **zoom_get_meeting** / **zoom_create_meeting** / **zoom_update_meeting** / **zoom_delete_meeting** – Meeting CRUD
- **zoom_list_recordings** – List cloud recordings for a user
- **zoom_list_meeting_participants** – List participants of a past meeting
- **zoom_list_meeting_registrants** – List registrants for a scheduled meeting

## Setup

1. Create a Server-to-Server OAuth app in the [Zoom Marketplace](https://marketplace.zoom.us/).

2. Set the required environment variable:
   ```bash
   export ZOOM_ACCESS_TOKEN=your-server-to-server-oauth-token
   ```

## Use Case

Example: "List all meetings scheduled for this week, check which ones have no registrants, and send a reminder to the organizer."
