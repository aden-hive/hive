"""Hourly scheduler for batch triage analysis."""

import logging
from apscheduler.schedulers.background import BackgroundScheduler

from app.database import get_session, ProcessedIssue
from app.github_client import github_client
from app.triage import should_analyze_issue, analyze_issue
from app.notifier import send_digest

logger = logging.getLogger(__name__)


def run_hourly_analysis():
    """Execute the hourly triage loop."""
    logger.info("Starting hourly triage analysis...")
    session = get_session()
    
    try:
        # Fetch recent issues using configurable lookback window
        from app.config import settings
        issues = github_client.get_recent_issues(minutes=settings.lookback_window_minutes)
        issue_numbers = [f"#{issue['number']}" for issue in issues]
        logger.info(f"Found {len(issues)} recent issues: {', '.join(issue_numbers) if issues else 'none'}")
        
        # Filter candidates
        candidates = [issue for issue in issues if should_analyze_issue(issue, session)]
        candidate_numbers = [f"#{issue['number']}" for issue in candidates]
        logger.info(f"Analyzing {len(candidates)} candidates: {', '.join(candidate_numbers) if candidates else 'none'}")
        
        # Analyze each candidate
        high_value_issues = []
        for issue in candidates:
            try:
                full_data = github_client.get_issue_with_comments(issue["number"])
                result = analyze_issue(full_data, session)
                if result:
                    high_value_issues.append(result)
            except Exception as e:
                logger.error(f"Error analyzing issue #{issue['number']}: {e}")
        
        # Check for zombie issues (stale assignees)
        stale_issues = github_client.get_stale_assigned_issues(days=14)
        logger.info(f"Found {len(stale_issues)} stale assigned issues")
        
        # Send digest if we have results
        if high_value_issues or stale_issues:
            if high_value_issues:
                logger.info(f"Found {len(high_value_issues)} high-value issues")
            send_digest(high_value_issues, stale_issues)
            
            # Mark as reported
            for item in high_value_issues:
                processed = session.query(ProcessedIssue).filter_by(
                    issue_id=item["issue_id"]
                ).first()
                if processed:
                    processed.reported_in_digest = True
            session.commit()
        else:
            logger.info("No high-value issues found this hour")
    
    except Exception as e:
        logger.error(f"Error in hourly analysis: {e}")
    finally:
        session.close()


def start_scheduler(interval_minutes: int = 60):
    """Start the background scheduler."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_hourly_analysis,
        'interval',
        minutes=interval_minutes,
        id='hourly_triage'
    )
    scheduler.start()
    logger.info(f"Scheduler started (interval: {interval_minutes} minutes)")
    return scheduler
