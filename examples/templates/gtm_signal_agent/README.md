# GTM Signal Intelligence Agent

A forever-alive pipeline that automates the full top-of-funnel GTM flow:

- **ICP intake**: Collect Ideal Customer Profile, target signals, and outreach preferences.
- **Signal scanning**: Uses Exa/news/web search to find buying signals from ICP-matched companies.
- **Lead enrichment**: Finds and enriches decision-makers via Apollo.
- **Opportunity scoring**: Scores each opportunity (0–100) and routes by score (hot / warm / cold).
- **Outreach drafting**: Drafts short, signal-specific outreach emails.
- **Human-in-the-loop approval**: Sales reps can approve, edit, or skip drafts before sending/CRM sync.
- **Pipeline actions**: Creates/updates HubSpot contacts and deals.
- **Weekly digest**: Periodic summarization of signals and activity.

## Setup

Requires the following environment variables (if real tools are used):
- `EXA_API_KEY` (for signal scanning)
- `APOLLO_API_KEY` (for lead enrichment)
- `HUBSPOT_ACCESS_TOKEN` (for CRM upsert)

## Usage

Run the agent in TUI mode:
```bash
make run-agent template=gtm_signal_agent
```

Or using the CLI directly:
```bash
python -m examples.templates.gtm_signal_agent tui
```
