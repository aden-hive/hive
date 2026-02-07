"""Webhook handlers for real-time ingestion."""

from fastapi import APIRouter, Request, HTTPException

from app.database import get_session
from app.github_client import github_client
from app.llm import generate_summary
from app.memory import issue_memory

router = APIRouter()


@router.post("/github")
async def github_webhook(request: Request):
    """Handle GitHub webhook events."""
    event_type = request.headers.get("X-GitHub-Event")
    payload = await request.json()
    
    if event_type == "issues":
        await handle_issue_event(payload)
    elif event_type == "issue_comment":
        await handle_comment_event(payload)
    
    return {"status": "ok"}


async def handle_issue_event(payload: dict):
    """Process issue opened/edited events."""
    action = payload.get("action")
    if action not in ["opened", "edited"]:
        return
    
    issue = payload["issue"]
    issue_id = str(issue["number"])
    
    # Fetch full data including timeline
    full_data = github_client.get_issue_with_comments(issue["number"])
    timeline = github_client.get_issue_timeline(issue["number"])
    
    # Import timeline parser
    from app.timeline_parser import extract_pr_info_from_timeline, build_outcome_text
    
    # Extract PR information
    pr_refs = extract_pr_info_from_timeline(timeline)
    pr_statuses = []
    for pr_ref in pr_refs[:5]:
        try:
            pr_details = github_client.get_pr_details(pr_ref["pr_number"])
            pr_statuses.append({
                "pr_number": pr_ref["pr_number"],
                "is_merged": pr_details.get("merged", False),
                "merged_at": pr_details.get("merged_at"),
                "state": pr_details.get("state")
            })
        except Exception:
            pass
    
    # Build full text with outcome
    full_text = f"{issue['title']}\n\n{issue['body'] or ''}"
    
    if full_data["comments"]:
        comments_text = "\n\n".join([c["body"] for c in full_data["comments"][:10]])
        full_text += f"\n\nComments:\n{comments_text}"
    
    # Add outcome
    outcome_text = build_outcome_text(pr_statuses)
    full_text += f"\n\nOUTCOME: {outcome_text}"
    
    # Generate summary
    summary = generate_summary(full_text)
    
    # Determine if has merged PR
    has_merged_pr = any(pr.get("is_merged") for pr in pr_statuses)
    
    # Extract label names and convert to comma-separated string
    labels = [label["name"] for label in issue.get("labels", [])]
    labels_str = ", ".join(labels) if labels else ""
    
    # Upsert to vector store
    issue_memory.upsert_issue(
        issue_id=issue_id,
        full_text=full_text,
        summary=summary,
        metadata={
            "title": issue["title"],
            "state": issue["state"],
            "has_merged_pr": has_merged_pr,
            "labels": labels_str,  # Store as comma-separated string
            "created_at": issue["created_at"]
        }
    )


async def handle_comment_event(payload: dict):
    """Process new comments on issues."""
    if payload.get("action") != "created":
        return
    
    issue = payload["issue"]
    issue_id = str(issue["number"])
    
    # Re-fetch and update the vector store
    full_data = github_client.get_issue_with_comments(issue["number"])
    full_text = f"{issue['title']}\n\n{issue['body'] or ''}"
    
    if full_data["comments"]:
        comments_text = "\n\n".join([c["body"] for c in full_data["comments"][:10]])
        full_text += f"\n\nComments:\n{comments_text}"
    
    # Regenerate summary
    summary = generate_summary(full_text)
    
    # Extract label names and convert to comma-separated string
    labels = [label["name"] for label in issue.get("labels", [])]
    labels_str = ", ".join(labels) if labels else ""
    
    # Update vector store
    issue_memory.upsert_issue(
        issue_id=issue_id,
        full_text=full_text,
        summary=summary,
        metadata={
            "title": issue["title"],
            "state": issue["state"],
            "labels": labels_str,  # Store as comma-separated string
            "created_at": issue["created_at"]
        }
    )
