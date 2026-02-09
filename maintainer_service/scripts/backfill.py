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
    
    print(f"Fetching issues since {since}...")
    
    from app.mcp_client import mcp_client
    
    all_issues = []
    page = 1
    
    while True:
        try:
            print(f"Fetching page {page}...")
            
            # Use the corrected mcp_client.get_issues method
            batch = mcp_client.get_issues(state="all", page=page, limit=100)
            
            if isinstance(batch, dict) and "error" in batch:
                print(f"Error fetching page {page}: {batch['error']}")
                break
                
            if not batch:
                break
                
            all_issues.extend(batch)
            print(f"Fetched {len(batch)} issues (Total: {len(all_issues)})")
            
            if len(batch) < 100:
                break
                
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
    
    # Filter by 'since' date client-side
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    filtered_issues = []
    for issue in all_issues:
        updated_at_str = issue.get("updated_at", "")
        if updated_at_str:
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            if updated_at >= since_dt:
                filtered_issues.append(issue)
    
    print(f"Filtered to {len(filtered_issues)} issues updated since {since}")
    all_issues = filtered_issues
    
    print(f"Total issues to process: {len(all_issues)}")
    
    # Process each issue
    # We can stick to serial processing or use ThreadPoolExecutor but call MCP tools
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def process_single_issue(idx, issue):
        """Process a single issue and return success status."""
        issue_number = issue["number"]
        # print(f"[{idx}/{len(all_issues)}] Processing issue #{issue_number}...", end="\r")
        
        try:
            # Fetch timeline via MCP
            timeline = mcp_client.get_issue_timeline(issue_number)
            if isinstance(timeline, dict) and "error" in timeline:
                # Fallback or empty if error
                timeline = []
            
            # Extract PR references
            pr_refs = extract_pr_info_from_timeline(timeline)
            
            # Fetch PR details for each reference
            pr_statuses = []
            for pr_ref in pr_refs[:5]:  # Limit to first 5 PRs
                try:
                    pr_details = mcp_client.get_pull_request(pr_ref["pr_number"])
                    if isinstance(pr_details, dict) and "error" not in pr_details:
                        pr_statuses.append({
                            "pr_number": pr_ref["pr_number"],
                            "is_merged": pr_details.get("merged", False),
                            "merged_at": pr_details.get("merged_at"),
                            "state": pr_details.get("state")
                        })
                except Exception:
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
            
            # Extract label names
            labels = [label["name"] for label in issue.get("labels", [])]
            labels_str = ", ".join(labels) if labels else ""
            
            # Upsert to ChromaDB via memory module (which uses MCP)
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
            
            return True, idx
        
        except Exception as e:
            return False, e
    
    # Use ThreadPoolExecutor for parallel processing
    max_workers = 10  # Reduced/Safe worker count for MCP calls
    success_count = 0
    
    print("Processing issues...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_issue, idx, issue): idx 
            for idx, issue in enumerate(all_issues, 1)
        }
        
        for future in as_completed(futures):
            success, result = future.result()
            if success:
                success_count += 1
                if result % 10 == 0:
                    print(f"Processed {result}/{len(all_issues)} issues...")
            else:
                print(f"Error: {result}")
    
    print(f"\n✅ Backfill complete! Successfully processed {success_count}/{len(all_issues)} issues.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical issues into ChromaDB")
    parser.add_argument("--days", type=int, default=30, help="Number of days to backfill (default: 30)")
    args = parser.parse_args()
    
    backfill_issues(days=args.days)
