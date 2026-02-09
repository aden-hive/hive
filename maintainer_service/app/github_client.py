"""GitHub API client using MCP tools.

This module provides a simplified interface to GitHub operations
using the aden_tools github_tool via MCP.
"""
from datetime import datetime, timedelta

from app.mcp_client import mcp_client


class GitHubClient:
    """Client for interacting with GitHub API via MCP tools."""
    
    def get_recent_issues(self, minutes: int = 65) -> list[dict]:
        """
        Fetch issues created in the last N minutes.
        
        Args:
            minutes: Lookback window
            
        Returns:
            List of issue dictionaries
        """
        since_dt = datetime.utcnow() - timedelta(minutes=minutes)
        
        # GitHub tool doesn't support 'since' parameter, so we fetch and filter client-side
        # Fetch recent pages to capture new issues
        all_issues = []
        for page in range(1, 4):  # Fetch first 3 pages (up to 90 issues)
            result = mcp_client.get_issues(state="open", page=page, limit=30)
            
            if isinstance(result, dict) and "error" in result:
                if page == 1:
                    raise Exception(f"GitHub API error: {result['error']}")
                break  # Stop if we hit an error on subsequent pages
            
            if not result:
                break
                
            all_issues.extend(result)
        
        # Filter by created_at
        recent_issues = []
        for issue in all_issues:
            created_at_str = issue.get("created_at", "")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if created_at.replace(tzinfo=None) >= since_dt:
                    recent_issues.append(issue)
        
        return recent_issues
    
    def get_issue_with_comments(self, issue_number: int) -> dict:
        """
        Fetch an issue with all its comments.
        
        Args:
            issue_number: Issue number
            
        Returns:
            Dict with 'issue' and 'comments' keys
        """
        issue = mcp_client.get_issue(issue_number=issue_number)
        comments = mcp_client.get_issue_comments(issue_number=issue_number)
        
        if isinstance(issue, dict) and "error" in issue:
            raise Exception(f"Failed to fetch issue: {issue['error']}")
        
        if isinstance(comments, dict) and "error" in comments:
            raise Exception(f"Failed to fetch comments: {comments['error']}")
        
        return {"issue": issue, "comments": comments}
    
    def get_issue_timeline(self, issue_number: int) -> list[dict]:
        """
        Fetch the full timeline of events for an issue.
        
        Args:
            issue_number: Issue number
            
        Returns:
            List of timeline events
        """
        result = mcp_client.get_issue_timeline(issue_number=issue_number)
        
        if isinstance(result, dict) and "error" in result:
            raise Exception(f"Failed to fetch timeline: {result['error']}")
        
        return result
    
    def get_pr_details(self, pr_number: int) -> dict:
        """
        Fetch pull request details including merge status.
        
        Args:
            pr_number: PR number
            
        Returns:
            PR details dict
        """
        result = mcp_client.get_pull_request(pr_number=pr_number)
        
        if isinstance(result, dict) and "error" in result:
            raise Exception(f"Failed to fetch PR: {result['error']}")
        
        return result

    def get_stale_assigned_issues(self, days: int = 14) -> list[dict]:
        """
        Fetch open issues that are assigned but haven't been updated in X days.
        
        Args:
            days: Number of days to consider stale
            
        Returns:
            List of stale assigned issues
        """
        stale_threshold = datetime.utcnow() - timedelta(days=days)
        stale_threshold_str = stale_threshold.isoformat() + "Z"
        
        # Fetch assigned issues
        result = mcp_client.get_issues(state="open", assignee="*", limit=100)
        
        if isinstance(result, dict) and "error" in result:
            raise Exception(f"GitHub API error: {result['error']}")
        
        all_issues = result
        
        # Filter for stale issues
        stale_issues = []
        for issue in all_issues:
            # Skip pull requests
            if "pull_request" in issue:
                continue
            
            updated_at = datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
            if updated_at.replace(tzinfo=None) < stale_threshold:
                stale_issues.append(issue)
        
        return stale_issues


# Global instance
github_client = GitHubClient()
