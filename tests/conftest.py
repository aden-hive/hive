"""Pytest configuration and fixtures."""

import pytest
import asyncio
from typing import Dict, Any


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_agent():
    """Sample agent for testing."""
    return {
        "id": "test-agent-1",
        "name": "Test Agent",
        "goal": "Test goal",
        "nodes": [
            {"id": "node-1", "type": "llm", "prompt": "Test"}
        ]
    }


@pytest.fixture
def sample_user():
    """Sample user for testing."""
    return {
        "id": "user-1",
        "email": "test@example.com",
        "name": "Test User",
        "roles": ["free"]
    }


@pytest.fixture
def auth_headers():
    """Sample auth headers."""
    return {
        "Authorization": "Bearer test-token"
    }


@pytest.fixture
def sample_config():
    """Sample configuration."""
    return {
        "environment": "test",
        "service": "test-service",
        "key": "test-key",
        "value": "test-value"
    }


@pytest.fixture
def sample_feature_flag():
    """Sample feature flag."""
    return {
        "name": "test_flag",
        "enabled": True,
        "rollout_percentage": 100,
        "rules": []
    }


# Performance testing markers
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "benchmark: mark test as benchmark test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
