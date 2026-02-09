"""Notification system for sending digests using MCP tools."""

import logging
import httpx

from app.config import settings
from app.mcp_client import mcp_client

logger = logging.getLogger(__name__)


def send_digest(issues: list[dict], stale_issues: list[dict] = None):
    """
    Send digest of high-value issues and zombie alerts.
    
    Args:
        issues: List of novel high-value issues
        stale_issues: List of stale assigned issues (zombie issues)
    """
    if stale_issues is None:
        stale_issues = []
    
    if settings.notification_email:
        send_email_digest(issues, stale_issues)
    
    if settings.slack_webhook_url:
        send_slack_digest(issues, stale_issues)


def send_email_digest(issues: list[dict], stale_issues: list[dict] = None):
    """Send email digest via MCP email tool."""
    if stale_issues is None:
        stale_issues = []
    
    try:
        # Group issues by category (based on labels)
        categorized = {
            "🐛 Bugs": [],
            "✨ Enhancements": [],
            "🔌 Integrations": [],
            "🔒 Security": [],
            "📚 Documentation": [],
            "🎯 Other": []
        }
        
        for issue in issues:
            # Extract labels from the issue (fetch from GitHub or pass in metadata)
            # For now, we'll categorize based on title/reasoning if labels aren't available
            # You can enhance this by passing labels in the issue dict
            labels = issue.get("labels", "").lower()
            
            if "bug" in labels or "critical" in labels:
                categorized["🐛 Bugs"].append(issue)
            elif "enhancement" in labels or "feature" in labels:
                categorized["✨ Enhancements"].append(issue)
            elif "integration" in labels or "tools" in labels:
                categorized["🔌 Integrations"].append(issue)
            elif "security" in labels:
                categorized["🔒 Security"].append(issue)
            elif "documentation" in labels:
                categorized["📚 Documentation"].append(issue)
            else:
                categorized["🎯 Other"].append(issue)
        
        # Sort issues within each category by Impact Score (Descending) for true priority
        for category in categorized:
            categorized[category].sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        
        # Build HTML email with categorization
        total_count = len(issues) + len(stale_issues)
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                h2 {{ color: #2c3e50; }}
                h3 {{ color: #34495e; margin-top: 25px; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
                
                /* Severity Flags */
                .severity-critical {{ background: #e74c3c; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
                .severity-high {{ background: #e67e22; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
                
                /* Issue Cards */
                .issue {{ margin: 15px 0; padding: 15px; background: #f8f9fa; border-left: 5px solid #bdc3c7; }}
                .impact-critical {{ border-left-color: #e74c3c; background: #fff5f5; }} /* Score > 90 */
                .impact-high {{ border-left-color: #e67e22; background: #fffcf5; }} /* Score > 80 */
                
                /* Zombie Alert Section */
                .zombie-section {{ margin-top: 40px; padding: 20px; background: #fff3cd; border: 2px solid #ffc107; border-radius: 5px; }}
                .zombie-header {{ color: #856404; font-size: 18px; font-weight: bold; margin-bottom: 10px; }}
                .zombie-issue {{ margin: 10px 0; padding-bottom: 10px; border-bottom: 1px solid #ffeeba; }}
                
                .issue-title {{ font-size: 16px; font-weight: bold; margin-bottom: 5px; display: block; }}
                .meta {{ color: #7f8c8d; font-size: 14px; margin: 5px 0; }}
                .summary {{ margin: 8px 0; }}
            </style>
        </head>
        <body>
            <h2>Hourly Issue Digest: {total_count} Items Requiring Attention</h2>
            <p>Issues are ranked by <strong>Impact Score</strong></p>
        """
        
        # Add issues by category
        for category, category_issues in categorized.items():
            if category_issues:
                html += f"<h3>{category} ({len(category_issues)})</h3>"
                for issue in category_issues:
                    impact = issue.get("impact_score", 0)
                    severity = issue.get("severity", "Low")
                    
                    # Determine CSS class based on impact
                    impact_class = ""
                    if impact >= 90: impact_class = "impact-critical"
                    elif impact >= 80: impact_class = "impact-high"
                    
                    # Severity Badge
                    severity_badge = ""
                    if severity in ["Current Critical", "Critical"]:
                        severity_badge = '<span class="severity-critical">CRITICAL</span>'
                    elif severity == "High":
                        severity_badge = '<span class="severity-high">HIGH</span>'
                    
                    html += f"""
                    <div class="issue {impact_class}">
                        <div class="issue-title">
                            {severity_badge} <a href="{issue['url']}">#{issue['number']}: {issue['title']}</a>
                        </div>
                        <div class="meta">
                            <strong>Impact Score: {impact}/100</strong> | Novelty: {issue['novelty_score']}/10 | Severity: {severity}
                        </div>
                        <div class="summary"><strong>Summary:</strong> {issue['summary']}</div>
                        <div class="reasoning"><strong>Analysis:</strong> {issue['reasoning']}</div>
                    </div>
                    """
        
        # Distinct Zombie Section (Prominent)
        if stale_issues:
            html += f"""
            <div class="zombie-section">
                <div class="zombie-header">⚠️ STALLED: Inactive Assignees ({len(stale_issues)})</div>
                <p>These issues are assigned but have had <strong>no activity for 14+ days</strong>. Maintainer intervention recommended.</p>
            """
            for issue in stale_issues:
                assignee_name = issue.get("assignee", {}).get("login", "Unknown") if issue.get("assignee") else "Unknown"
                html += f"""
                <div class="zombie-issue">
                    <div class="issue-title">
                        <a href="{issue['html_url']}">#{issue['number']}: {issue['title']}</a>
                    </div>
                    <div class="meta">
                        <strong>Assignee:</strong> @{assignee_name} | 
                        <strong>Last Updated:</strong> {issue['updated_at'][:10]}
                    </div>
                </div>
                """
            html += "</div>"
        
        html += """
        </body>
        </html>
        """
        
        # Send email via MCP tool
        result = mcp_client.send_email(
            to=settings.notification_email,
            subject=f"Hourly Issue Digest: {total_count} Items Requiring Attention",
            html=html,
            from_email=settings.smtp_username,
            provider="smtp"
        )
        
        if isinstance(result, dict) and result.get("success"):
            logger.info(f"Email digest sent to {settings.notification_email}")
        else:
            logger.error(f"Failed to send email: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def send_slack_digest(issues: list[dict]):
    """Send digest to Slack via webhook."""
    try:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Hourly Issue Digest: {len(issues)} High-Value Items"
                }
            }
        ]
        
        for issue in issues:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{issue['url']}|#{issue['number']}: {issue['title']}>*\n"
                            f"*Novelty:* {issue['novelty_score']}/10\n"
                            f"*Summary:* {issue['summary']}\n"
                            f"*Why:* {issue['reasoning']}"
                }
            })
            blocks.append({"type": "divider"})
        
        payload = {"blocks": blocks}
        
        with httpx.Client() as client:
            response = client.post(settings.slack_webhook_url, json=payload)
            response.raise_for_status()
        
        logger.info("Slack digest sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
