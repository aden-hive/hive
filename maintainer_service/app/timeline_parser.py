"""Helper functions for parsing GitHub timeline events."""

def extract_pr_info_from_timeline(timeline: list[dict]) -> list[dict]:
    """
    Extract linked PR information from timeline events.
    
    Args:
        timeline: List of timeline events from GitHub API
        
    Returns:
        List of dicts with keys: pr_number, is_merged, merged_at
    """
    pr_references = []
    
    for event in timeline:
        # Look for cross-referenced events (when this issue was referenced by a PR)
        if event.get("event") == "cross-referenced":
            source = event.get("source", {})
            if source.get("type") == "issue" and "pull_request" in source.get("issue", {}):
                pr_number = source["issue"]["number"]
                pr_references.append({
                    "pr_number": pr_number,
                    "event_created_at": event.get("created_at")
                })
    
    return pr_references


def build_outcome_text(pr_statuses: list[dict]) -> str:
    """
    Build outcome text describing PR resolution status.
    
    Args:
        pr_statuses: List of dicts with pr_number, is_merged, merged_at
        
    Returns:
        Human-readable outcome text
    """
    if not pr_statuses:
        return "No linked PRs found."
    
    merged_prs = [pr for pr in pr_statuses if pr.get("is_merged")]
    closed_prs = [pr for pr in pr_statuses if not pr.get("is_merged") and pr.get("state") == "closed"]
    open_prs = [pr for pr in pr_statuses if pr.get("state") == "open"]
    
    parts = []
    if merged_prs:
        pr_nums = ", ".join([f"#{pr['pr_number']}" for pr in merged_prs])
        parts.append(f"SOLVED: Merged via PR(s) {pr_nums}.")
    
    if closed_prs:
        pr_nums = ", ".join([f"#{pr['pr_number']}" for pr in closed_prs])
        parts.append(f"FAILED_ATTEMPT: PR(s) {pr_nums} closed without merge.")
    
    if open_prs:
        pr_nums = ", ".join([f"#{pr['pr_number']}" for pr in open_prs])
        parts.append(f"IN_PROGRESS: PR(s) {pr_nums} still open.")
    
    return " ".join(parts)
