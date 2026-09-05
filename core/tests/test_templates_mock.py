import sys
from pathlib import Path

import pytest

# Add examples/templates to sys.path to allow template package imports
repo_root = Path(__file__).parents[2]
templates_root = repo_root / "examples" / "templates"
if str(templates_root) not in sys.path:
    sys.path.append(str(templates_root))

TEMPLATES = [
    "competitive_intel_agent",
    "deep_research_agent",
    "email_inbox_management",
    "email_reply_agent",
    "job_hunter",
    "local_business_extractor",
    "meeting_scheduler",
    "sdr_agent",
    "tech_news_reporter",
    "twitter_news_agent",
    "vulnerability_assessment",
]


@pytest.mark.parametrize("template_name", TEMPLATES)
def test_template_mock_setup(template_name: str) -> None:
    import importlib

    # Import the default_agent from agent.py of the template
    module = importlib.import_module(f"{template_name}.agent")
    agent = module.default_agent

    # Verify _setup with mock_mode=True configures the agent correctly
    agent._setup(mock_mode=True)

    # Retrieve the configured runtime (some agents use _agent_runtime, others use _executor)
    runtime = getattr(agent, "_agent_runtime", None) or getattr(agent, "_executor", None)
    assert runtime is not None

    # Verify the LLM provider is indeed MockLLMProvider
    llm = getattr(runtime, "_llm", None) or getattr(runtime, "llm", None)
    assert llm is not None
    assert llm.__class__.__name__ == "MockLLMProvider"
