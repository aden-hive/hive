"""Test fixtures for SecOps Alert Triage Agent."""

import pytest
from pathlib import Path


@pytest.fixture
def agent():
    """Create a SecOpsAlertTriageAgent instance for testing."""
    from exports.secops_alert_triage_agent import SecOpsAlertTriageAgent

    return SecOpsAlertTriageAgent()


@pytest.fixture
def sample_datadog_alert():
    """Sample Datadog alert for testing."""
    return {
        "alert_id": "dd-12345",
        "title": "Suspicious login detected",
        "severity": "high",
        "host": "prod-web-01",
        "timestamp": "2026-03-11T10:00:00Z",
        "tags": ["security", "authentication"],
        "text": "Multiple failed login attempts from unusual location",
    }


@pytest.fixture
def sample_normalized_alert():
    """Sample normalized alert for testing."""
    return {
        "alert_id": "test-001",
        "source": "datadog",
        "timestamp": "2026-03-11T10:00:00Z",
        "title": "Suspicious login detected",
        "description": "Multiple failed login attempts from unusual location",
        "severity": "high",
        "affected_asset": {
            "hostname": "prod-web-01",
            "ip": "10.0.0.1",
            "service": "web-api",
            "environment": "production",
        },
        "indicators": {
            "ips": ["192.168.1.100"],
            "domains": [],
            "hashes": [],
            "users": ["admin"],
        },
        "raw_alert": {},
    }


@pytest.fixture
def sample_suppression_rules():
    """Sample suppression rules for testing."""
    return {
        "known_ci_ips": {
            "description": "Known CI/CD IP ranges",
            "ips": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
            "action": "suppress",
        },
        "scheduled_scanners": {
            "description": "Approved vulnerability scanner signatures",
            "user_agents": ["Nessus", "Qualys", "Rapid7"],
            "action": "suppress",
        },
    }
