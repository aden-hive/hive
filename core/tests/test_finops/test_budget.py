"""Tests for the FinOps budget policy engine."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from framework.finops.budget import (
    BudgetAction,
    BudgetAlert,
    BudgetExceededError,
    BudgetPolicyEngine,
    get_policy_engine,
    reset_policy_engine,
)
from framework.finops.config import BudgetPolicy, BudgetThreshold, FinOpsConfig
from framework.finops.metrics import FinOpsCollector, reset_collector


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global state before and after each test."""
    reset_collector()
    reset_policy_engine()
    yield
    reset_collector()
    reset_policy_engine()


class TestBudgetPolicy:
    """Tests for BudgetPolicy dataclass."""

    def test_default_values(self):
        """Test default policy values."""
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
        )
        assert policy.enabled is True
        assert policy.max_tokens_per_run is None
        assert policy.max_cost_usd_per_run is None
        assert len(policy.thresholds) == 0

    def test_to_dict(self):
        """Test policy serialization."""
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
            max_tokens_per_run=10000,
            thresholds=[
                BudgetThreshold(threshold=50, action=BudgetAction.WARN),
            ],
        )

        data = policy.to_dict()

        assert data["name"] == "test-policy"
        assert data["max_tokens_per_run"] == 10000
        assert len(data["thresholds"]) == 1


class TestBudgetPolicyEngine:
    """Tests for BudgetPolicyEngine."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = BudgetPolicyEngine()
        assert len(engine.list_policies()) == 0

    def test_add_policy(self):
        """Test adding a policy."""
        engine = BudgetPolicyEngine()
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
        )

        engine.add_policy(policy)

        policies = engine.list_policies()
        assert len(policies) == 1
        assert policies[0].name == "test-policy"

    def test_remove_policy(self):
        """Test removing a policy."""
        engine = BudgetPolicyEngine()
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
        )
        engine.add_policy(policy)

        result = engine.remove_policy("agent", "test-agent")

        assert result is True
        assert len(engine.list_policies()) == 0

    def test_remove_nonexistent_policy(self):
        """Test removing a policy that doesn't exist."""
        engine = BudgetPolicyEngine()
        result = engine.remove_policy("agent", "nonexistent")
        assert result is False

    def test_get_policy(self):
        """Test getting a policy by scope."""
        engine = BudgetPolicyEngine()
        policy = BudgetPolicy(
            name="test-policy",
            scope="agent",
            scope_id="test-agent",
        )
        engine.add_policy(policy)

        found = engine.get_policy("agent", "test-agent")

        assert found is not None
        assert found.name == "test-policy"

    def test_check_run_budget_no_policy(self):
        """Test budget check when no policy exists."""
        engine = BudgetPolicyEngine()
        alerts = engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=1000,
            cost_usd=0.01,
        )
        assert len(alerts) == 0

    def test_check_run_budget_under_threshold(self):
        """Test budget check when under threshold."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=10000,
                thresholds=[
                    BudgetThreshold(threshold=80, action=BudgetAction.WARN),
                ],
            )
        )

        alerts = engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=5000,
            cost_usd=0.01,
        )

        assert len(alerts) == 0

    def test_check_run_budget_over_threshold(self):
        """Test budget check when over threshold."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=10000,
                thresholds=[
                    BudgetThreshold(threshold=50, action=BudgetAction.WARN),
                ],
            )
        )

        alerts = engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=8000,
            cost_usd=0.01,
        )

        assert len(alerts) == 1
        assert alerts[0].action == BudgetAction.WARN

    def test_check_run_budget_kill_action(self):
        """Test budget check with KILL action."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="cost-limit",
                scope="agent",
                scope_id="test-agent",
                max_cost_usd_per_run=0.10,
                thresholds=[
                    BudgetThreshold(threshold=100, action=BudgetAction.KILL),
                ],
            )
        )

        with pytest.raises(BudgetExceededError) as exc_info:
            engine.check_run_budget(
                run_id="run-1",
                agent_id="test-agent",
                tokens=1000,
                cost_usd=0.15,
            )

        assert "Cost" in str(exc_info.value)
        assert exc_info.value.alert.action == BudgetAction.KILL

    def test_check_run_budget_wildcard_policy(self):
        """Test budget check with wildcard policy."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="global-limit",
                scope="agent",
                scope_id="*",
                max_tokens_per_run=5000,
                thresholds=[
                    BudgetThreshold(threshold=100, action=BudgetAction.WARN),
                ],
            )
        )

        alerts = engine.check_run_budget(
            run_id="run-1",
            agent_id="any-agent",
            tokens=6000,
            cost_usd=0.01,
        )

        assert len(alerts) == 1

    def test_check_burn_rate(self):
        """Test burn rate checking."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="burn-rate-limit",
                scope="agent",
                scope_id="test-agent",
                burn_rate_threshold=1000.0,
                thresholds=[
                    BudgetThreshold(threshold=100, action=BudgetAction.WARN),
                ],
            )
        )

        alerts = engine.check_burn_rate(
            run_id="run-1",
            agent_id="test-agent",
            burn_rate=1500.0,
        )

        assert len(alerts) == 1
        assert "Burn rate" in alerts[0].message

    def test_get_alerts(self):
        """Test getting alerts."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=1000,
                thresholds=[
                    BudgetThreshold(threshold=50, action=BudgetAction.WARN),
                ],
            )
        )

        engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=800,
            cost_usd=0.01,
        )

        alerts = engine.get_alerts()
        assert len(alerts) == 1

    def test_clear_alerts(self):
        """Test clearing alerts."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=1000,
                thresholds=[
                    BudgetThreshold(threshold=50, action=BudgetAction.WARN),
                ],
            )
        )

        engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=800,
            cost_usd=0.01,
        )

        engine.clear_alerts()
        alerts = engine.get_alerts()
        assert len(alerts) == 0

    def test_load_policies_from_file(self):
        """Test loading policies from file."""
        engine = BudgetPolicyEngine()

        policies_data = {
            "policies": [
                {
                    "name": "policy-1",
                    "scope": "agent",
                    "scope_id": "test-agent",
                    "max_tokens_per_run": 10000,
                    "thresholds": [
                        {"threshold": 50, "action": "warn"},
                        {"threshold": 100, "action": "kill"},
                    ],
                },
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(policies_data, f)
            f.flush()

            count = engine.load_policies_from_file(f.name)

        assert count == 1
        policies = engine.list_policies()
        assert len(policies) == 1

    def test_save_policies_to_file(self):
        """Test saving policies to file."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="policy-1",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=10000,
            )
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            engine.save_policies_to_file(f.name)

            with open(f.name) as saved:
                data = json.load(saved)

        assert "policies" in data
        assert len(data["policies"]) == 1

    def test_custom_action_handler(self):
        """Test registering custom action handlers."""
        engine = BudgetPolicyEngine()

        custom_alerts = []

        def custom_handler(alert: BudgetAlert):
            custom_alerts.append(alert)

        engine.register_handler(BudgetAction.WARN, custom_handler)

        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=1000,
                thresholds=[
                    BudgetThreshold(threshold=50, action=BudgetAction.WARN),
                ],
            )
        )

        engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=800,
            cost_usd=0.01,
        )

        assert len(custom_alerts) == 1

    def test_disabled_policy(self):
        """Test that disabled policies are not checked."""
        engine = BudgetPolicyEngine()
        engine.add_policy(
            BudgetPolicy(
                name="token-limit",
                scope="agent",
                scope_id="test-agent",
                max_tokens_per_run=1000,
                enabled=False,
                thresholds=[
                    BudgetThreshold(threshold=50, action=BudgetAction.WARN),
                ],
            )
        )

        alerts = engine.check_run_budget(
            run_id="run-1",
            agent_id="test-agent",
            tokens=800,
            cost_usd=0.01,
        )

        assert len(alerts) == 0

    def test_get_policy_engine_singleton(self):
        """Test that get_policy_engine returns a singleton."""
        engine1 = get_policy_engine()
        engine2 = get_policy_engine()
        assert engine1 is engine2


class TestBudgetAlert:
    """Tests for BudgetAlert dataclass."""

    def test_default_values(self):
        """Test default alert values."""
        alert = BudgetAlert(
            policy_name="test",
            scope="agent",
            scope_id="test-agent",
            action=BudgetAction.WARN,
            threshold=1000,
            current_value=800,
            threshold_percentage=80.0,
            message="Test alert",
        )

        assert alert.run_id == ""
        assert alert.agent_id == ""
        assert alert.timestamp is not None
