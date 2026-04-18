# SavvyCal Tool

This module integrates with the [SavvyCal API](https://savvycal.com/docs/api) to allow agents to seamlessly manage scheduling workflows, meeting links, and bookings.

## Why SavvyCal for Agents?
Agents often need to arrange meetings, handle inbound requests, or audit schedules. A native SavvyCal integration lets agents dynamically generate personal scheduling links for prospects, fetch required attendee information, and gracefully cancel or reschedule meetings based on incoming context.

## Setup

A Personal Access Token is required to authenticate.

1. Log in to your SavvyCal account at https://savvycal.com
2. Go to **Settings > Developer** (https://savvycal.com/users/settings/developer)
3. Click **New Personal Access Token**
4. Give the token a name (e.g., "Hive Agent")
5. Copy the token — it won't be shown again.
6. Export the token to your environment before running the server:
   ```bash
   export SAVVYCAL_API_KEY="your_token_here"
   ```

## Supported Endpoints

### 1. `savvycal_list_links`
Lists all scheduling links for the authenticated user.
- **Parameters:** None
- **Returns:** List of scheduling link metadata.

### 2. `savvycal_get_link`
Retrieves a specific scheduling link by its slug.
- **Parameters:** `slug` (str) — e.g., "intro-call"
- **Returns:** Detailed link information.

### 3. `savvycal_create_link`
Creates a new scheduling link. Useful for dynamic link generation.
- **Parameters:** 
  - `name` (str) — Display name (e.g., "30-min Intro")
  - `duration` (int) — Meeting duration in minutes
  - `event_type` (str) — Associated event type slug
- **Returns:** Created link details including ID and URL.

### 4. `savvycal_update_link`
Updates properties of an existing link.
- **Parameters:** `slug` (str, required), `name` (str, optional), `duration` (int, optional), `event_type` (str, optional)
- **Returns:** Updated link details.

### 5. `savvycal_delete_link`
Deletes a scheduling link.
- **Parameters:** `slug` (str)
- **Returns:** Deletion confirmation dict.

### 6. `savvycal_list_bookings`
Lists bookings with optional filters.
- **Parameters:** 
  - `start_date` (str, optional) — ISO 8601 string
  - `end_date` (str, optional) — ISO 8601 string
  - `status` (str, optional) - scheduled, cancelled, or completed
- **Returns:** List of matching bookings.

### 7. `savvycal_get_booking`
Retrieves granular details about a specific booking.
- **Parameters:** `booking_id` (str)
- **Returns:** Full payload for the booking.

### 8. `savvycal_cancel_booking`
Cancels an existing booking.
- **Parameters:** 
  - `booking_id` (str)
  - `reason` (str, optional) - Plaintext reasoning sent to attendees.
- **Returns:** Cancellation confirmation dict.


## Agent Workflow Examples

### 1. Sales Development Representative (SDR) Agent
**Task:** Qualify inbound leads and book an introductory call.
**Workflow:** 
1. The agent evaluates an inbound email thread. 
2. If qualified, the agent generates a distinct temporal link via `savvycal_create_link` (e.g. "Acme Corp Discovery - 30 minutes"). 
3. The agent sends the link URL back in the email thread.

### 2. Personal Assistant Agent
**Task:** Monitor the assistant's schedule and gracefully cancel no-longer-relevant meetings.
**Workflow:**
1. The agent pulls yesterday's priority shift using internal context. 
2. Uses `savvycal_list_bookings` to scan next week. 
3. Identifies an obsolete sync call, runs `savvycal_cancel_booking` with the reasoning: "Priority context shifted to Q4".

### 3. Recruiting Coordinator Agent
**Task:** Send candidate interview loops dynamically.
**Workflow:**
1. Candidate clears technical screening.
2. The agent fetches the "technical-onsite" event type parameters via `savvycal_list_links`. 
3. Agent texts/emails the slug parameter and candidate-specific prep payload, ensuring accurate timing matches.
