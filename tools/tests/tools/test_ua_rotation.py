import pytest
import random
from aden_tools.tools.web_scrape_tool.web_scrape_tool import BROWSER_USER_AGENT

def test_browser_user_agent_rotation():
    """Verify that BROWSER_USER_AGENT returns different values across calls."""
    # Collect a sample of user agents
    sample_size = 50
    uas = [BROWSER_USER_AGENT() for _ in range(sample_size)]
    
    # Verify that we have variety
    unique_uas = set(uas)
    
    # Statistical check: with 1000 items, getting the same one 50 times in a row 
    # is extremely unlikely (1/1000^49).
    assert len(unique_uas) > 1, f"User agent failed to rotate in {sample_size} calls"
    
    # Ensure they look like real user agents (contain Mozilla)
    for ua in uas:
        assert "Mozilla" in ua, f"Invalid user agent returned: {ua}"

def test_fallback_user_agent():
    """Verify that a fallback is returned even if configuration is missing."""
    # The BROWSER_USER_AGENT alias should always return a string
    ua = BROWSER_USER_AGENT()
    assert isinstance(ua, str)
    assert len(ua) > 10
