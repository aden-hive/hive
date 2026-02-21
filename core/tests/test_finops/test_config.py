"""Tests for the FinOps config module."""

from __future__ import annotations

import os

import pytest

from framework.finops.config import (
    BudgetAction,
    BudgetPolicy,
    BudgetThreshold,
    FinOpsConfig,
)


class TestBudgetAction:
    """Tests for BudgetAction enum."""

    def test_action_values(self):
        """Test that action values are correct."""
        assert BudgetAction.WARN.value == "warn"
        assert BudgetAction.DEGRADE.value == "degrade"
        assert BudgetAction.THROTTLE.value == "throttle"
        assert BudgetAction.KILL.value == "kill"


class TestBudgetThreshold:
    """Tests for BudgetThreshold dataclass."""

    def test_default_values(self):
        """Test default threshold values."""
        threshold = BudgetThreshold(threshold=50, action=BudgetAction.WARN)
        assert threshold.threshold == 50
        assert threshold.action == BudgetAction.WARN
        assert threshold.message == ""


class TestBudgetPolicy:
    """Tests for BudgetPolicy dataclass."""

    def test_default_values(self):
        """Test default policy values."""
        policy = BudgetPolicy(
            name="test",
            scope="agent",
            scope_id="test-agent",
        )
        assert policy.enabled is True
        assert policy.max_tokens_per_run is None
        assert policy.max_cost_usd_per_run is None
        assert policy.max_tokens_per_minute is None
        assert policy.burn_rate_threshold is None
        assert len(policy.thresholds) == 0

    def test_to_dict(self):
        """Test policy serialization."""
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
            max_tokens_per_run=10000,
            max_cost_usd_per_run=1.0,
            thresholds=[
                BudgetThreshold(threshold=50, action=BudgetAction.WARN, message="50% reached"),
                BudgetThreshold(threshold=100, action=BudgetAction.KILL, message="Budget exceeded"),
            ],
            enabled=False,
        )

        data = policy.to_dict()

        assert data["name"] == "test-policy"
        assert data["scope"] == "agent"
        assert data["scope_id"] == "test-agent"
        assert data["max_tokens_per_run"] == 10000
        assert data["max_cost_usd_per_run"] == 1.0
        assert data["enabled"] is False
        assert len(data["thresholds"]) == 2
        assert data["thresholds"][0]["action"] == "warn"
        assert data["thresholds"][1]["action"] == "kill"


class TestFinOpsConfig:
    """Tests for FinOpsConfig dataclass."""

    def test_default_values(self):
        """Test default config values."""
        config = FinOpsConfig()
        assert config.enabled is True
        assert config.prometheus_enabled is True
        assert config.prometheus_port == 9090
        assert config.prometheus_host == "0.0.0.0"
        assert config.otel_enabled is False
        assert config.otel_endpoint is None
        assert config.otel_service_name == "hive-agent"
        assert config.runaway_detection_enabled is True
        assert config.runaway_failure_threshold == 3
        assert config.runaway_burn_rate_multiplier == 2.0
        assert config.cost_estimation_enabled is True
        assert len(config.budget_policies) == 0

    def test_from_env_defaults(self, monkeypatch):
        """Test loading config from environment with defaults."""
        for key in list(os.environ.keys()):
            if key.startswith("HIVE_") or key.startswith("OTEL_"):
                monkeypatch.delenv(key, raising=False)

        config = FinOpsConfig.from_env()

        assert config.enabled is True
        assert config.prometheus_enabled is True
        assert config.prometheus_port == 9090

    def test_from_env_custom_values(self, monkeypatch):
        """Test loading config from environment with custom values."""
        monkeypatch.setenv("HIVE_FINOPS_ENABLED", "false")
        monkeypatch.setenv("HIVE_PROMETHEUS_ENABLED", "false")
        monkeypatch.setenv("HIVE_PROMETHEUS_PORT", "8888")
        monkeypatch.setenv("HIVE_PROMETHEUS_HOST", "127.0.0.1")
        monkeypatch.setenv("HIVE_OTEL_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-agent")
        monkeypatch.setenv("HIVE_RUNAWAY_FAILURE_THRESHOLD", "5")
        monkeypatch.setenv("HIVE_RUNAWAY_BURN_RATE_MULTIPLIER", "3.0")

        config = FinOpsConfig.from_env()

        assert config.enabled is False
        assert config.prometheus_enabled is False
        assert config.prometheus_port == 8888
        assert config.prometheus_host == "127.0.0.1"
        assert config.otel_enabled is True
        assert config.otel_endpoint == "http://localhost:4317"
        assert config.otel_service_name == "custom-agent"
        assert config.runaway_failure_threshold == 5
        assert config.runaway_burn_rate_multiplier == 3.0

    def test_to_dict(self):
        """Test config serialization."""
        config = FinOpsConfig(
            enabled=True,
            prometheus_enabled=True,
            prometheus_port=9090,
            budget_policies=[
                BudgetPolicy(name="test", scope="agent", scope_id="test-agent"),
            ],
        )

        data = config.to_dict()

        assert data["enabled"] is True
        assert data["prometheus_enabled"] is True
        assert data["prometheus_port"] == 9090
        assert len(data["budget_policies"]) == 1

    def test_with_budget_policies(self):
        """Test config with budget policies."""
        policies = [
            BudgetPolicy(
                name="agent-budget",
                scope="agent",
                scope_id="my-agent",
                max_cost_usd_per_run=1.0,
                thresholds=[
                    BudgetThreshold(threshold=80, action=BudgetAction.WARN),
                    BudgetThreshold(threshold=100, action=BudgetAction.KILL),
                ],
            ),
            BudgetPolicy(
                name="node-budget",
                scope="node",
                scope_id="expensive-node",
                max_tokens_per_run=50000,
            ),
        ]

        config = FinOpsConfig(budget_policies=policies)

        assert len(config.budget_policies) == 2
        assert config.budget_policies[0].name == "agent-budget"
        assert config.budget_policies[1].name == "node-budget"
