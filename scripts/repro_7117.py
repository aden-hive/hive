import sys
import os
from unittest.mock import patch

# Add core to path
sys.path.append(os.path.abspath("core"))

from framework.config import get_max_tokens, get_max_context_tokens, DEFAULT_MAX_TOKENS, DEFAULT_MAX_CONTEXT_TOKENS


def test_null_config_fallbacks():
    print("Testing null config fallbacks...")

    # Mock get_hive_config to return null values
    mock_config = {
        "llm": {"max_tokens": None, "max_context_tokens": None},
        "worker_llm": {"max_tokens": None, "max_context_tokens": None},
    }

    with patch("framework.config.get_hive_config", return_value=mock_config):
        max_t = get_max_tokens()
        max_ctx = get_max_context_tokens()

        print(f"max_tokens: {max_t} (expected {DEFAULT_MAX_TOKENS})")
        print(f"max_context_tokens: {max_ctx} (expected {DEFAULT_MAX_CONTEXT_TOKENS})")

        assert max_t == DEFAULT_MAX_TOKENS, f"Expected {DEFAULT_MAX_TOKENS}, got {max_t}"
        assert max_ctx == DEFAULT_MAX_CONTEXT_TOKENS, f"Expected {DEFAULT_MAX_CONTEXT_TOKENS}, got {max_ctx}"

    print("Test passed!")


if __name__ == "__main__":
    try:
        test_null_config_fallbacks()
    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)
