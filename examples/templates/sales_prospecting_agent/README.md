# B2B Sales Prospecting & Outreach Agent

This agent template automates the end-to-end workflow for B2B sales outreach, from lead generation to sending personalized emails.

## Workflow

1.  **Intake**: Collects target audience details, value proposition, and outreach goals from the user.
2.  **Lead Search**: Uses the Apollo tool to find relevant leads matching the target audience.
3.  **Company Research**: Scrapes company websites and uses Apollo enrichment to find business context and "hooks" for personalization.
4.  **Draft Email**: Generates highly personalized outreach emails for each lead.
5.  **Human Approval**: Presents drafts to the user for review, allowing for feedback and iterations.
6.  **Send Email**: Sends the approved emails via the Email tool (Resend or Gmail).

## Prerequisites

-   **Apollo API Key**: Required for lead search and enrichment.
-   **Email Provider API Key**:
    -   `RESEND_API_KEY` for Resend.
    -   Google OAuth credentials for Gmail.
-   **Anthropic/OpenAI API Key**: For the LLM reasoning (depending on your configuration).

## Configuration

Settings can be adjusted in `config.py`:
-   `max_leads_per_search`: Limit the number of leads per run.
-   `email_provider`: Choose between `resend` and `gmail`.
-   `email_from`: Set the sender address.

## How to Run

```powershell
python -m examples.templates.sales_prospecting_agent
```

## success Criteria

The agent's performance is measured by lead relevance, research depth, email personalization quality, and successful delivery.
