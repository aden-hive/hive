"""Mock tools for Autonomous SRE Agent — no real infra required."""

import json
import random
from datetime import datetime

# Mock log templates per alert type
_MOCK_LOGS = {
    "high_error_rate": [
        {"ts": "2024-01-15T10:01:02Z", "level": "ERROR", "msg": "DatabaseConnectionPool exhausted: timeout after 30s", "count": 847},
        {"ts": "2024-01-15T10:01:05Z", "level": "ERROR", "msg": "HTTP 500: upstream connect error or disconnect/reset before headers", "count": 1203},
        {"ts": "2024-01-15T10:01:08Z", "level": "WARN",  "msg": "Retry attempt 3/3 failed for db-primary:5432", "count": 412},
        {"ts": "2024-01-15T10:01:10Z", "level": "ERROR", "msg": "Circuit breaker OPEN for payment-db after 10 consecutive failures", "count": 1},
    ],
    "latency_spike": [
        {"ts": "2024-01-15T10:01:02Z", "level": "WARN",  "msg": "p99 latency 4200ms exceeds SLO threshold 500ms", "count": 1},
        {"ts": "2024-01-15T10:01:04Z", "level": "ERROR", "msg": "GC pause duration 3800ms — heap utilization 94%", "count": 23},
        {"ts": "2024-01-15T10:01:07Z", "level": "WARN",  "msg": "Thread pool queue depth 2400 — workers saturated", "count": 1},
    ],
    "oom": [
        {"ts": "2024-01-15T10:01:01Z", "level": "ERROR", "msg": "java.lang.OutOfMemoryError: Java heap space", "count": 1},
        {"ts": "2024-01-15T10:01:01Z", "level": "ERROR", "msg": "Container killed: OOMKilled — memory limit 2Gi exceeded", "count": 1},
        {"ts": "2024-01-15T10:01:03Z", "level": "WARN",  "msg": "Memory usage 1.98Gi/2Gi — approaching limit", "count": 47},
    ],
    "cpu_overload": [
        {"ts": "2024-01-15T10:01:00Z", "level": "WARN",  "msg": "CPU throttling detected: 78% of CPU budget consumed", "count": 1},
        {"ts": "2024-01-15T10:01:03Z", "level": "ERROR", "msg": "Request timeout: processing exceeded 10s limit", "count": 334},
        {"ts": "2024-01-15T10:01:06Z", "level": "WARN",  "msg": "Infinite loop suspected in order-processing worker", "count": 1},
    ],
}

_DEFAULT_LOGS = [
    {"ts": "2024-01-15T10:01:00Z", "level": "ERROR", "msg": "Unexpected service failure — check downstream dependencies", "count": 1},
    {"ts": "2024-01-15T10:01:02Z", "level": "WARN",  "msg": "Health check failing for 3 consecutive intervals", "count": 3},
]

# Mock historical incidents
_HISTORICAL_INCIDENTS = {
    "database": {
        "id": "INC-2847",
        "date": "2023-11-03",
        "root_cause": "Database connection pool exhausted due to slow queries from missing index",
        "resolution": "Added index on orders.created_at, increased pool size from 20 to 50",
        "similarity": 92,
    },
    "memory": {
        "id": "INC-3102",
        "date": "2023-12-18",
        "root_cause": "Memory leak in session cache — unbounded growth over 6h",
        "resolution": "Deployed hotfix with TTL on session cache entries, rolled pods",
        "similarity": 88,
    },
    "cpu": {
        "id": "INC-2991",
        "date": "2023-11-28",
        "root_cause": "Runaway background job processing malformed CSV — infinite retry loop",
        "resolution": "Added dead-letter queue, deployed fix with input validation",
        "similarity": 85,
    },
    "latency": {
        "id": "INC-3044",
        "date": "2023-12-05",
        "root_cause": "GC pressure from large object allocation in report generation",
        "resolution": "Switched to streaming response, tuned JVM heap flags",
        "similarity": 79,
    },
}


def fetch_mock_logs(service: str, alert_type: str) -> str:
    """Return mock log entries for the given service and alert type."""
    key = alert_type.lower().replace(" ", "_").replace("-", "_")
    logs = _MOCK_LOGS.get(key, _DEFAULT_LOGS)
    return json.dumps({
        "service": service,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "log_count": len(logs),
        "entries": logs,
    })


def get_similar_incidents(service: str, symptoms: str) -> str:
    """Return mock historical incidents matching the symptoms."""
    symptoms_lower = symptoms.lower()
    matches = []
    for keyword, incident in _HISTORICAL_INCIDENTS.items():
        if keyword in symptoms_lower or keyword in service.lower():
            matches.append(incident)
    return json.dumps(matches[:2])  # return top 2


def draft_slack_message(channel: str, service: str, root_cause: str, severity: str, remediation: str) -> str:
    """Return a mock Slack message draft."""
    emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
    return json.dumps({
        "channel": channel,
        "status": "draft",
        "message": (
            f"{emoji} *[{severity.upper()}] Incident — {service}*\n"
            f"*Root Cause:* {root_cause}\n"
            f"*Remediation:* {remediation}\n"
            f"*Status:* Investigating — auto-resolution in progress"
        ),
    })


def draft_jira_ticket(service: str, root_cause: str, severity: str, steps: str) -> str:
    """Return a mock Jira ticket draft."""
    ticket_id = f"OPS-{random.randint(1000, 9999)}"
    return json.dumps({
        "ticket_id": ticket_id,
        "status": "draft",
        "title": f"[{severity.upper()}] {service} — {root_cause[:60]}",
        "description": f"**Root Cause:** {root_cause}\n\n**Remediation Steps:**\n{steps}",
        "severity": severity,
        "labels": ["incident", "auto-generated", service],
    })


def store_incident_outcome(service: str, root_cause: str, severity: str,
                           confidence: int, resolution: str, timestamp: str) -> str:
    """Mock store — returns confirmation of storage."""
    return json.dumps({
        "stored": True,
        "incident_id": f"INC-{random.randint(4000, 9999)}",
        "service": service,
        "root_cause": root_cause,
        "severity": severity,
        "confidence": confidence,
        "resolution": resolution,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": "Incident stored in long-term memory for future similarity matching.",
    })
