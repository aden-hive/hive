"""Property-based tests."""

import pytest
from hypothesis import given, settings
from core.framework.testing.property_based import (
    agent_strategy,
    config_strategy,
    user_attributes_strategy
)


class TestPropertyBased:
    """Property-based test suite."""

    @given(agent_data=agent_strategy())
    @settings(max_examples=50)
    def test_agent_properties(self, agent_data):
        """Test agent properties hold for various inputs."""
        assert agent_data["name"] is not None
        assert len(agent_data["name"]) <= 100
        assert agent_data["goal"] is not None
        assert isinstance(agent_data["nodes"], list)

    @given(config=config_strategy())
    @settings(max_examples=50)
    def test_config_serialization(self, config):
        """Test config is always JSON serializable."""
        import json
        json.dumps(config)  # Should not raise

    @given(attrs=user_attributes_strategy())
    @settings(max_examples=30)
    def test_user_attributes(self, attrs):
        """Test user attributes structure."""
        assert "user_id" in attrs
        assert "email" in attrs
        assert "@" in attrs["email"]
