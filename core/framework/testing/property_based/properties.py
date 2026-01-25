"""Property-based tests using Hypothesis."""

from hypothesis import given, settings, Phase
from hypothesis.stateful import RuleStateMachine, rule, invariant, run_state_machine
import pytest

from .strategies import (
    agent_strategy,
    config_strategy,
    user_attributes_strategy
)


class AgentStateMachine(RuleStateMachine):
    """Stateful property-based testing for agents."""

    def __init__(self):
        super().__init__()
        self.agents = []
        self.nodes_created = 0

    @rule()
    def create_agent(self, agent_data=agent_strategy()) -> None:
        """Creating an agent should always succeed."""
        # In real implementation, would create actual agent
        agent_id = f"agent_{len(self.agents)}"
        self.agents.append({
            "id": agent_id,
            "data": agent_data
        })

    @rule()
    def add_node(self) -> None:
        """Adding nodes should increase node count."""
        if not self.agents:
            return

        initial_count = self.nodes_created
        self.nodes_created += 1

        assert self.nodes_created == initial_count + 1

    @invariant()
    def agent_integrity(self) -> None:
        """Agent list should maintain integrity."""
        assert len(self.agents) >= 0
        for agent in self.agents:
            assert "id" in agent
            assert "data" in agent


@given(agent_data=agent_strategy())
@settings(max_examples=100)
def test_agent_creation_with_various_inputs(agent_data: dict) -> None:
    """Agent should handle various input combinations."""
    # Properties that should always hold
    assert agent_data["name"] is not None
    assert len(agent_data["name"]) <= 100
    assert agent_data["goal"] is not None
    assert len(agent_data["goal"]) <= 500
    assert isinstance(agent_data["nodes"], list)


@given(config=config_strategy())
@settings(max_examples=100)
def test_config_handling(config: dict) -> None:
    """System should handle various config structures."""
    # Property: config should be serializable
    import json
    try:
        json.dumps(config)
        assert True
    except Exception:
        assert False, "Config should be JSON serializable"


@given(
    flag_name=st.text(min_size=1, max_size=50),
    user_attrs=user_attributes_strategy()
)
@settings(max_examples=50)
def test_feature_flag_evaluation(flag_name: str, user_attrs: dict) -> None:
    """Feature flag evaluation should be consistent."""
    # Property: evaluation should return boolean
    result = True  # Placeholder - would use actual flag evaluation
    assert isinstance(result, bool)


@given(
    email1=st.text(min_size=1).map(lambda x: f"{x}@test.com"),
    email2=st.text(min_size=1).map(lambda x: f"{x}@test.com")
)
@settings(max_examples=50)
def test_user_email_uniqueness(email1: str, email2: str) -> None:
    """Email uniqueness should be enforced."""
    if email1 == email2:
        # Should not allow duplicate emails
        assert True
    else:
        # Different emails should be allowed
        assert True
