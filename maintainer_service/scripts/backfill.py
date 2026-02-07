"""Script to backfill historical issues into ChromaDB."""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import init_db
from app.github_client import github_client
from app.llm import generate_summary
from app.memory import issue_memory
from app.timeline_parser import extract_pr_info_from_timeline, build_outcome_text


def backfill_issues(days: int = 30):
    """
    Backfill historical issues into the vector store.
    
    Args:
        days: Number of days of history to backfill
    """
    print(f"Starting backfill for last {days} days...")
    init_db()
    
    # Calculate the date threshold
    since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    
    # Fetch all issues (including closed)
    print(f"Fetching issues since {since}...")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import httpx
    
    def fetch_page(page_num):
        """Fetch a single page of issues."""
        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                f"{github_client.base_url}/repos/{github_client.repo}/issues",
                headers=github_client.headers,
                params={
                    "state": "all",
                    "since": since,
                    "per_page": 100,
                    "page": page_num,
                    "sort": "updated",
                    "direction": "desc"
                }
            )
            response.raise_for_status()
            return response.json()
    
    # First, fetch page 1 to estimate total pages
    page_1_issues = fetch_page(1)
    all_issues = page_1_issues
    print(f"Fetched page 1: {len(page_1_issues)} issues")
    
    # If we got 100 issues, there are likely more pages
    if len(page_1_issues) == 100:
        # Estimate max pages (GitHub typically has a cap, so we'll fetch up to 50 pages in parallel)
        max_pages = 50
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            # Submit fetch jobs for pages 2 onwards
            futures = {
                executor.submit(fetch_page, page): page 
                for page in range(2, max_pages + 1)
            }
            
            # Collect results as they complete
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    issues = future.result()
                    if issues:
                        all_issues.extend(issues)
                        print(f"Fetched page {page_num}: {len(issues)} issues")
                    else:
                        # Empty page means we've reached the end
                        break
                except Exception as e:
                    print(f"Error fetching page {page_num}: {e}")
    
    print(f"Total issues to process: {len(all_issues)}")
    
    # Process each issue in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def process_single_issue(idx, issue):
        """Process a single issue and return success status."""
        issue_number = issue["number"]
        print(f"[{idx}/{len(all_issues)}] Processing issue #{issue_number}...")
        
        try:
            # Fetch timeline
            timeline = github_client.get_issue_timeline(issue_number)
            
            # Extract PR references
            pr_refs = extract_pr_info_from_timeline(timeline)
            
            # Fetch PR details for each reference
            pr_statuses = []
            for pr_ref in pr_refs[:5]:  # Limit to first 5 PRs
                try:
                    pr_details = github_client.get_pr_details(pr_ref["pr_number"])
                    pr_statuses.append({
                        "pr_number": pr_ref["pr_number"],
                        "is_merged": pr_details.get("merged", False),
                        "merged_at": pr_details.get("merged_at"),
                        "state": pr_details.get("state")
                    })
                except Exception as e:
                    pass
            
            # Build rich text
            full_text = f"{issue['title']}\n\n{issue['body'] or ''}"
            
            # Add outcome context
            outcome_text = build_outcome_text(pr_statuses)
            full_text += f"\n\nOUTCOME: {outcome_text}"
            
            # Generate summary
            summary = generate_summary(full_text)
            
            # Determine if has merged PR
            has_merged_pr = any(pr.get("is_merged") for pr in pr_statuses)
            
            # Extract label names and convert to comma-separated string
            labels = [label["name"] for label in issue.get("labels", [])]
            labels_str = ", ".join(labels) if labels else ""
            
            # Upsert to ChromaDB
            issue_memory.upsert_issue(
                issue_id=str(issue_number),
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
            
            print(f"  ✓ Processed (Merged PR: {has_merged_pr})")
            return True
        
        except Exception as e:
            print(f"  ✗ Error processing issue #{issue_number}: {e}")
            return False
    
    # Use ThreadPoolExecutor for parallel processing
    max_workers = 500  # Adjust based on rate limits
    success_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_single_issue, idx, issue): idx 
            for idx, issue in enumerate(all_issues, 1)
        }
        
        # Wait for completion
        for future in as_completed(futures):
            if future.result():
                success_count += 1
    
    print(f"\n✅ Backfill complete! Successfully processed {success_count}/{len(all_issues)} issues.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical issues into ChromaDB")
    parser.add_argument("--days", type=int, default=30, help="Number of days to backfill (default: 30)")
    args = parser.parse_args()
    
    backfill_issues(days=args.days)
