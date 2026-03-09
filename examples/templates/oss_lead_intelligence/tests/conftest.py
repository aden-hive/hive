"""
OSS Lead Intelligence Agent - Test Configuration.

Provides pytest fixtures for testing the agent.
"""

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[4]
for _p in ["examples/templates", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AGENT_PATH = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="session")
def agent_module():
    """Import the agent package for structural validation."""
    import importlib

    return importlib.import_module(Path(AGENT_PATH).name)


@pytest.fixture(scope="session")
def agent():
    """Create an OSSLeadIntelligenceAgent instance for testing."""
    from oss_lead_intelligence import OSSLeadIntelligenceAgent

    return OSSLeadIntelligenceAgent()


@pytest.fixture(scope="session")
def runner_loaded():
    """Load the agent through AgentRunner (structural validation)."""
    from framework.runner.runner import AgentRunner
    from framework.credentials.models import CredentialError

    try:
        return AgentRunner.load(AGENT_PATH)
    except CredentialError:
        pytest.skip("Credentials not configured")


@pytest.fixture
def sample_github_profile():
    """Sample GitHub profile data for testing."""
    return {
        "username": "johndoe",
        "name": "John Doe",
        "bio": "Software engineer interested in AI and open source",
        "company": "Acme Inc",
        "location": "San Francisco, CA",
        "email": "john@acme.com",
        "public_repos": 25,
        "followers": 150,
        "following": 80,
        "github_url": "https://github.com/johndoe",
        "avatar_url": "https://avatars.githubusercontent.com/u/12345",
        "starred_repo": "adenhq/hive",
    }


@pytest.fixture
def sample_icp_criteria():
    """Sample ICP criteria for testing."""
    return {
        "titles": [
            "VP Engineering",
            "CTO",
            "Engineering Manager",
            "Director of Engineering",
        ],
        "company_sizes": ["51-200", "201-500", "501-1000"],
        "industries": ["technology", "software", "fintech"],
        "min_repos": 3,
    }


@pytest.fixture
def sample_enriched_lead():
    """Sample enriched lead data for testing."""
    return {
        "username": "johndoe",
        "name": "John Doe",
        "title": "VP of Engineering",
        "company": "Acme Inc",
        "company_domain": "acme.com",
        "company_size": "201-500",
        "industry": "technology",
        "email": "john@acme.com",
        "linkedin_url": "https://linkedin.com/in/johndoe",
        "location": "San Francisco, CA",
        "github_url": "https://github.com/johndoe",
        "public_repos": 25,
        "followers": 150,
        "lead_score": 92,
        "enrichment_source": "apollo",
        "starred_repo": "adenhq/hive",
    }
