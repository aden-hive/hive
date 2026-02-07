"""GitHub API client for fetching issues and managing webhooks."""

import httpx
from datetime import datetime, timedelta

from app.config import settings


class GitHubClient:
    """Client for interacting with GitHub API."""
    
    def __init__(self):
        self.base_url = "https://api.github.com"
        self.repo = f"{settings.github_repo_owner}/{settings.github_repo_name}"
        self.headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def get_recent_issues(self, minutes: int = 65) -> list[dict]:
        """
        Fetch issues created in the last N minutes.
        
        Args:
            minutes: Lookback window
            
        Returns:
            List of issue dictionaries
        """
        since = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat() + "Z"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.base_url}/repos/{self.repo}/issues",
                headers=self.headers,
                params={
                    "state": "open",
                    "since": since,
                    "per_page": 100,
                    "sort": "created",
                    "direction": "desc"
                }
            )
            response.raise_for_status()
            return response.json()
    
    def get_issue_with_comments(self, issue_number: int) -> dict:
        """
        Fetch an issue with all its comments.
        
        Args:
            issue_number: Issue number
            
        Returns:
            Dict with 'issue' and 'comments' keys
        """
        with httpx.Client(timeout=30.0) as client:
            # Get issue
            issue_resp = client.get(
                f"{self.base_url}/repos/{self.repo}/issues/{issue_number}",
                headers=self.headers
            )
            issue_resp.raise_for_status()
            issue = issue_resp.json()
            
            # Get comments
            comments_resp = client.get(
                f"{self.base_url}/repos/{self.repo}/issues/{issue_number}/comments",
                headers=self.headers
            )
            comments_resp.raise_for_status()
            comments = comments_resp.json()
            
            return {"issue": issue, "comments": comments}
    
    def get_issue_timeline(self, issue_number: int) -> list[dict]:
        """
        Fetch the full timeline of events for an issue.
        
        Args:
            issue_number: Issue number
            
        Returns:
            List of timeline events
        """
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.base_url}/repos/{self.repo}/issues/{issue_number}/timeline",
                headers={**self.headers, "Accept": "application/vnd.github.mockingbird-preview+json"}
            )
            response.raise_for_status()
            return response.json()
    
    def get_pr_details(self, pr_number: int) -> dict:
        """
        Fetch pull request details including merge status.
        
        Args:
            pr_number: PR number
            
        Returns:
            PR details dict
        """
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.base_url}/repos/{self.repo}/pulls/{pr_number}",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()


    def get_stale_assigned_issues(self, days: int = 14) -> list[dict]:
        """
        Fetch open issues that are assigned but haven't been updated in X days.
        
        Args:
            days: Number of days to consider stale
            
        Returns:
            List of stale assigned issues
        """
        from datetime import datetime, timedelta
        
        stale_threshold = datetime.utcnow() - timedelta(days=days)
        stale_threshold_str = stale_threshold.isoformat() + "Z"
        
        with httpx.Client(timeout=30.0) as client:
            # Fetch assigned issues
            response = client.get(
                f"{self.base_url}/repos/{self.repo}/issues",
                headers=self.headers,
                params={
                    "state": "open",
                    "assignee": "*",  # Any assignee
                    "per_page": 100,
                    "sort": "updated",
                    "direction": "asc"  # Oldest first
                }
            )
            response.raise_for_status()
            all_issues = response.json()
            
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


github_client = GitHubClient()
