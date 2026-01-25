"""Property-based testing strategies with Hypothesis."""

from typing import Dict, Any
from hypothesis import strategies as st
import sys
sys.path.append("../..")
from framework.schemas import Agent, Node


def agent_strategy() -> st.SearchStrategy[Dict]:
    """Generate random valid agent configurations."""
    return st.fixed_dictionaries({
        "name": st.text(min_size=1, max_size=100, alphabet='abcdefghijklmnopqrstuvwxyz'),
        "goal": st.text(min_size=1, max_size=500),
        "nodes": st.lists(node_strategy(), max_size=10, min_size=0)
    })


def node_strategy() -> st.SearchStrategy[Dict]:
    """Generate random valid node configurations."""
    return st.one_of(
        llm_node_strategy(),
        function_node_strategy(),
        router_node_strategy()
    )


def llm_node_strategy() -> st.SearchStrategy[Dict]:
    """Generate random LLM node configurations."""
    return st.fixed_dictionaries({
        "id": st.text(min_size=1, alphabet='0123456789'),
        "type": st.just("llm"),
        "prompt": st.text(min_size=1, max_size=2000),
        "model": st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]),
        "temperature": st.floats(min_value=0.0, max_value=2.0),
        "max_tokens": st.integers(min_value=1, max_value=4000)
    })


def function_node_strategy() -> st.SearchStrategy[Dict]:
    """Generate random function node configurations."""
    return st.fixed_dictionaries({
        "id": st.text(min_size=1, alphabet='0123456789'),
        "type": st.just("function"),
        "function_name": st.sampled_from(["search", "calculate", "transform"]),
        "parameters": st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.one_of(st.text(), st.integers(), st.floats(), st.booleans()),
            min_size=0,
            max_size=5
        )
    })


def router_node_strategy() -> st.SearchStrategy[Dict]:
    """Generate random router node configurations."""
    return st.fixed_dictionaries({
        "id": st.text(min_size=1, alphabet='0123456789'),
        "type": st.just("router"),
        "routes": st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=5
        )
    })


def config_strategy() -> st.SearchStrategy[Dict]:
    """Generate random configuration dictionaries."""
    return st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet='abcdefghijklmnopqrstuvwxyz'),
        values=st.one_of(
            st.text(),
            st.integers(min_value=-1000, max_value=1000),
            st.floats(min_value=-1000.0, max_value=1000.0),
            st.booleans(),
            st.lists(st.text())
        ),
        min_size=0,
        max_size=20
    )


def user_attributes_strategy() -> st.SearchStrategy[Dict]:
    """Generate random user attributes for feature flag testing."""
    return st.fixed_dictionaries({
        "user_id": st.text(min_size=1, alphabet='0123456789abcdef'),
        "email": st.text(min_size=1, max_size=100).map(lambda x: f"{x}@example.com"),
        "tier": st.sampled_from(["free", "pro", "enterprise"]),
        "age": st.integers(min_value=18, max_value=100)
    })
