"""Core triage logic for analyzing issues."""

from datetime import datetime, timedelta

from app.database import get_session, ProcessedIssue
from app.github_client import github_client
from app.llm import analyze_novelty
from app.memory import issue_memory


def should_analyze_issue(issue: dict, session) -> bool:
    """
    Determine if an issue should be analyzed based on filters.
    
    Args:
        issue: GitHub issue dict
        session: Database session
        
    Returns:
        True if issue should be analyzed
    """
    # Filter 1: Ignore closed issues
    if issue["state"] == "closed":
        return False
    
    # Filter 2: Ignore spam labels
    labels = [label["name"] for label in issue.get("labels", [])]
    spam_labels = {"invalid", "wontfix", "question", "spam"}
    if any(label in spam_labels for label in labels):
        return False
    
    # Filter 3: Ignore old "updates" (only analyze recently created issues)
    created_at = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
    if datetime.now(created_at.tzinfo) - created_at > timedelta(hours=24):
        return False
    
    # Filter 4: Check if already reported
    issue_id = str(issue["number"])
    processed = session.query(ProcessedIssue).filter_by(issue_id=issue_id).first()
    if processed and processed.reported_in_digest:
        return False
    
    return True


def analyze_issue(issue_data: dict, session) -> dict | None:
    """
    Analyze a single issue for novelty and store in ChromaDB.
    
    Args:
        issue_data: Dict with 'issue' and 'comments' keys
        session: Database session
        
    Returns:
        Analysis result dict if novel, None otherwise
    """
    issue = issue_data["issue"]
    comments = issue_data["comments"]
    issue_id = str(issue["number"])
    
    # Fetch timeline for rich context
    from app.timeline_parser import extract_pr_info_from_timeline, build_outcome_text
    timeline = github_client.get_issue_timeline(issue["number"])
    
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
    
    # Build full thread with outcome
    full_text = f"{issue['title']}\n\n{issue['body'] or ''}"
    if comments:
        comment_text = "\n\n".join([c["body"] for c in comments[:10]])
        full_text += f"\n\nComments:\n{comment_text}"
    
    # Add outcome context
    outcome_text = build_outcome_text(pr_statuses)
    full_text += f"\n\nOUTCOME: {outcome_text}"
    
    # Find similar issues
    similar = issue_memory.find_similar(full_text, n_results=5, exclude_id=issue_id)
    similar_summaries = [s["metadata"].get("summary", "") for s in similar if s["metadata"].get("summary")]
    
    # LLM analysis
    # LLM analysis
    from app.llm import analyze_novelty, generate_summary
    analysis = analyze_novelty(full_text, similar_summaries)
    summary = analysis.get("one_sentence_summary", "")
    
    # Determine if has merged PR
    has_merged_pr = any(pr.get("is_merged") for pr in pr_statuses)
    
    # Extract labels
    labels = [label["name"] for label in issue.get("labels", [])]
    labels_str = ", ".join(labels) if labels else ""
    
    # Upsert to ChromaDB (ensure knowledge base is complete)
    issue_memory.upsert_issue(
        issue_id=issue_id,
        full_text=full_text,
        summary=summary,
        metadata={
            "title": issue["title"],
            "state": issue["state"],
            "has_merged_pr": has_merged_pr,
            "labels": labels_str,
            "created_at": issue["created_at"]
        }
    )
    
    # Save to SQLite database
    processed = ProcessedIssue(
        issue_id=issue_id,
        novelty_score=analysis.get("novelty_score"),
        is_duplicate=analysis.get("is_semantic_duplicate", False),
        last_analyzed_at=datetime.utcnow(),
        short_summary=summary
    )
    session.merge(processed)
    session.commit()
    
    # Calculate Impact Score (0-100)
    # Base: Novelty * 10
    novelty = analysis.get("novelty_score", 0)
    impact_score = novelty * 10
    
    # Severity Multiplier
    severity = analysis.get("severity", "Low")
    if severity == "Current Critical":
        impact_score += 20
    elif severity == "High":
        impact_score += 10
    
    # Cap at 100
    impact_score = min(impact_score, 100)
    
    # Return if high value (Novelty >= 8 OR Impact >= 70)
    if (novelty >= 8 or impact_score >= 80) and not analysis.get("is_semantic_duplicate"):
        return {
            "issue_id": issue_id,
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["html_url"],
            "novelty_score": novelty,
            "impact_score": impact_score,
            "severity": severity,
            "summary": analysis["one_sentence_summary"],
            "reasoning": analysis.get("reasoning", ""),
            "labels": labels_str
        }
    
    return None
