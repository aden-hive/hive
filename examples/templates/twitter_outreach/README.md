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

# Run the workflow
PYTHONPATH=core:exports uv run python -m twitter_outreach run

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

## Business Value

- **Personalized outreach** — Each email references the recipient's actual interests, recent posts, and bio, moving beyond generic templates that get ignored
- **Time savings** — Automates the research-draft-review cycle that typically takes 20-30 minutes per recipient down to a single guided session
- **Higher response rates** — Personalization based on real social signals consistently outperforms batch email approaches, driving meaningful engagement
- **Approval workflow** — Human-in-the-loop review at the draft stage ensures every message meets your standards before sending, preventing embarrassing mistakes
- **Reusable pattern** — The research-to-personalized-action pipeline adapts to LinkedIn outreach, partnership proposals, investor emails, or any scenario where context-aware communication matters

## Customization Guide

- **Change data source** — Swap Twitter/X research for LinkedIn, GitHub, or company websites by editing the `research` node system prompt and tools in `nodes/__init__.py`
- **Email provider** — Replace the `send_email` tool with your preferred email service (SendGrid, Mailgun, SMTP) by updating the tool implementation in your MCP server
- **Tone adjustment** — Edit the `draft-review` node system prompt to match your communication style (formal, casual, technical) or add brand voice guidelines
- **Multi-recipient** — Extend the intake node to accept a list of handles and loop the research-draft-send pipeline, creating a batch outreach workflow with per-recipient personalization
