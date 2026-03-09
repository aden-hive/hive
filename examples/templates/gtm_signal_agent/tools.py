"""Tool integrations for GTM Signal Intelligence Agent."""

import json
from framework.runner.tool_registry import tool

@tool(description="Search Exa for buying signals.")
def exa_search(query: str, num_results: int = 5) -> str:
    """
    Search Exa (or mock if no key) for buying signals based on a query.
    
    Args:
        query: The search query for buying signals (e.g. "company just raised funding").
        num_results: The number of results to return.
    """
    # Hybrid MVP: Simulate Exa call
    results = [
        {
            "title": f"Recent Signal related to: {query}",
            "url": "https://example.com/signal",
            "text": "The company just announced a major product launch and is looking to expand their sales team."
        }
    ]
    return json.dumps(results)

@tool(description="Fetch decision-maker contacts for a given domain.")
def apollo_enrichment(domain: str) -> str:
    """
    Fetch decision-maker contacts for a given domain via Apollo.
    
    Args:
        domain: The company domain to enrich (e.g. "example.com").
    """
    # Hybrid MVP: Simulate Apollo call
    contacts = [
        {
            "name": "Jane Doe",
            "title": "VP of Sales",
            "email": "jane@example.com",
            "linkedin": "https://linkedin.com/in/janedoe"
        }
    ]
    return json.dumps({"domain": domain, "contacts": contacts})

@tool(description="Create or update a contact and deal in HubSpot.")
def hubspot_upsert(email: str, company: str, score: int) -> str:
    """
    Create or update a contact and deal in HubSpot.
    
    Args:
        email: Contact's email address.
        company: Company name.
        score: Opportunity score.
    """
    return f"Successfully upserted {email} at {company} into HubSpot with score {score}."

@tool(description="Create a draft email in Gmail.")
def create_gmail_draft(to_email: str, subject: str, body: str) -> str:
    """
    Create a draft email in Gmail.
    
    Args:
        to_email: Recipient email address.
        subject: Email subject.
        body: Email body content.
    """
    return f"Created Gmail draft for {to_email}."

@tool(description="Send a notification to a Slack channel.")
def send_slack_notification(channel: str, message: str) -> str:
    """
    Send a notification to a Slack channel.
    
    Args:
        channel: Slack channel name.
        message: Message content.
    """
    return f"Sent Slack notification to {channel}."

@tool(description="Generate a Cal.com booking link.")
def generate_cal_com_link(meeting_type: str = "intro") -> str:
    """
    Generate a Cal.com booking link for the given meeting type.
    
    Args:
        meeting_type: Type of meeting (e.g., "intro", "demo").
    """
    return f"https://cal.com/sales-team/{meeting_type}"
