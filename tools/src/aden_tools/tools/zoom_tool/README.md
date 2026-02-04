# Zoom Tool

Enables agents to schedule and manage Zoom meetings.

## Setup
1. Create a "Server-to-Server OAuth" app at [marketplace.zoom.us](https://marketplace.zoom.us/).
2. Get your Account ID, Client ID, and Client Secret.
3. Set environment variables:
   - `ZOOM_ACCOUNT_ID`
   - `ZOOM_CLIENT_ID`
   - `ZOOM_CLIENT_SECRET`

## Functions
- `create_meeting`: Schedule a new call.
- `list_meetings`: See upcoming calls.
- `get_meeting_details`: Check status of a specific call.