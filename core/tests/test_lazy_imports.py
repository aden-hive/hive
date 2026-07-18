"""Regression tests for lazy package exports and startup optimization."""

import importlib
import sys


def _reset_framework_modules() -> None:
    for name in list(sys.modules):
        if name == "framework" or name.startswith("framework."):
            sys.modules.pop(name, None)


def test_framework_top_level_exports_are_lazy() -> None:
    _reset_framework_modules()
 
    framework = importlib.import_module("framework")

    assert "ColonyRuntime" not in framework.__dict__
    assert "AgentLoader" not in framework.__dict__

    assert framework.ColonyRuntime.__name__ == "ColonyRuntime"
    assert framework.AgentLoader.__name__ == "AgentLoader"


def test_agent_loop_exports_are_lazy() -> None:
    _reset_framework_modules()

    agent_loop = importlib.import_module("framework.agent_loop")

    assert "ConversationStore" not in agent_loop.__dict__
    assert "AgentContext" not in agent_loop.__dict__

    assert agent_loop.ConversationStore.__name__ == "ConversationStore"
    assert agent_loop.AgentContext.__name__ == "AgentContext"
