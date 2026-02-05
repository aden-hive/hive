# Twitter Outreach Agent

Personalized email outreach powered by Twitter/X research.

## What it does

1. **Intake** — Collects the target's Twitter handle, outreach purpose, and recipient email
2. **Research** — Searches and scrapes the target's Twitter/X profile for bio, tweets, interests
3. **Draft & Review** — Crafts a personalized email and presents it for your approval (with iteration)
4. **Send** — Sends the approved email

## Usage

```bash
# Validate the agent structure
PYTHONPATH=core:exports uv run python -m twitter_outreach validate

# Show agent info
PYTHONPATH=core:exports uv run python -m twitter_outreach info

# Run in mock mode (no API calls)
PYTHONPATH=core:exports uv run python -m twitter_outreach run --mock

# Launch the TUI
PYTHONPATH=core:exports uv run python -m twitter_outreach tui

# Interactive shell
PYTHONPATH=core:exports uv run python -m twitter_outreach shell
```

## Architecture

```
intake → research → draft-review → send
```

## Tools Used

- `web_search` — Search for Twitter profiles and public info
- `web_scrape` — Read Twitter/X profile pages
- `send_email` — Send the approved outreach email

## Nodes

| Node | Type | Client-Facing | Description |
|------|------|:---:|-------------|
| `intake` | event_loop | Yes | Collect target info from user |
| `research` | event_loop | No | Research Twitter/X profile |
| `draft-review` | event_loop | Yes | Draft email, iterate with user |
| `send` | event_loop | No | Send approved email |

## Constraints

- **No Spam** — No spammy language, clickbait, or aggressive sales tactics
- **Approval Required** — Never sends without explicit user approval
- **Tone** — Professional, authentic, conversational
- **Privacy** — Only uses publicly available information
