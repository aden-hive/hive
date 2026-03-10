"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.graph.edge import DEFAULT_MAX_TOKENS

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"
logger = logging.getLogger(__name__)


def get_hive_config() -> dict[str, Any]:
    """Load hive configuration from ~/.hive/configuration.json."""
    if not HIVE_CONFIG_FILE.exists():
        return {}
    try:
        with open(HIVE_CONFIG_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Failed to load Hive config %s: %s",
            HIVE_CONFIG_FILE,
            e,
        )
        return {}


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def get_available_providers() -> dict[str, dict[str, Any]]:
    """Detect all available LLM providers based on environment variables.
    
    Returns:
        Dictionary of provider_name -> {
            "name": Display name,
            "api_key": the key or None,
            "status": "available" or "needs_check",
            "models": list of available models,
            "default_model": default model to use,
            "free_tier": boolean indicating if free tier exists
        }
    """
    available = {}
    
    # Check Gemini (free tier available)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        available["gemini"] = {
            "name": "Google Gemini",
            "api_key": gemini_key,
            "status": "available",
            "models": ["gemini-3-flash-preview", "gemini-3.1-pro-preview"],
            "default_model": "gemini-3-flash-preview",
            "free_tier": True
        }
    
    # Check Anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        available["anthropic"] = {
            "name": "Anthropic Claude",
            "api_key": anthropic_key,
            "status": "needs_check",  # Will be verified when used
            "models": [
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-3-5-sonnet-20240620"
            ],
            "default_model": "claude-3-haiku-20240307",
            "free_tier": False
        }
    
    # Check OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        available["openai"] = {
            "name": "OpenAI GPT",
            "api_key": openai_key,
            "status": "needs_check",
            "models": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o"],
            "default_model": "gpt-3.5-turbo",
            "free_tier": False
        }
    
    # Check Groq (free tier)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        available["groq"] = {
            "name": "Groq (Fast, Free Tier)",
            "api_key": groq_key,
            "status": "available",
            "models": ["mixtral-8x7b-32768", "llama3-70b-8192", "llama3-8b-8192"],
            "default_model": "mixtral-8x7b-32768",
            "free_tier": True
        }
    
    # Check Cerebras (free tier)
    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if cerebras_key:
        available["cerebras"] = {
            "name": "Cerebras (Fast, Free Tier)",
            "api_key": cerebras_key,
            "status": "available",
            "models": ["llama3.1-8b", "llama3.1-70b"],
            "default_model": "llama3.1-8b",
            "free_tier": True
        }
    
    # Check DeepSeek
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if deepseek_key:
        available["deepseek"] = {
            "name": "DeepSeek",
            "api_key": deepseek_key,
            "status": "needs_check",
            "models": ["deepseek-chat", "deepseek-coder"],
            "default_model": "deepseek-chat",
            "free_tier": False
        }
    
    # Check Mistral
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if mistral_key:
        available["mistral"] = {
            "name": "Mistral AI",
            "api_key": mistral_key,
            "status": "needs_check",
            "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
            "default_model": "mistral-small-latest",
            "free_tier": False
        }
    
    return available


def format_provider_menu(providers: dict) -> str:
    """Format available providers into a user-friendly menu."""
    menu = "\n Available LLM Providers:\n"
    menu += "═" * 60 + "\n"
    
    for idx, (provider_id, info) in enumerate(providers.items(), 1):
        free_tag = "  FREE TIER" if info.get("free_tier") else "⚠️"
        status_icon = "" if info["status"] == "available" else "⚠️"
        menu += f"\n{idx}. {status_icon} {info['name']}{free_tag}"
        menu += f"\n   Models: {', '.join(info['models'][:3])}"
        if len(info['models']) > 3:
            menu += f" and {len(info['models'])-3} more"
        if info["status"] == "needs_check":
            menu += "\n     Will verify credits when used"
        menu += "\n"
    
    menu += "\n" + "═" * 60
    menu += "\n0. Keep using current selection and show error"
    return menu


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------


def get_preferred_model() -> str:
    """Return the user's preferred LLM model string.
    
    Format depends on provider:
    - For most providers: "provider/model" (e.g., "anthropic/claude-3-haiku-20240307")
    - For Gemini: just the model name (LiteLLM auto-detects)
    
    Returns:
        Model string that LiteLLM can use directly
    """
    llm = get_hive_config().get("llm", {})
    provider = llm.get("provider", "").lower()
    model = llm.get("model", "")
    
    # If we have both provider and model from config, use them
    if provider and model:
        # Special case for Gemini - LiteLLM handles it without provider prefix
        if provider == "gemini":
            logger.debug(f"Using Gemini model: {model}")
            return model
        # For other providers, use provider/model format
        logger.debug(f"Using {provider} model: {provider}/{model}")
        return f"{provider}/{model}"
    
    # If we have just a model from config, use it
    if model:
        logger.debug(f"Using model from config: {model}")
        return model
    
    # If we have just a provider, use a sensible default for that provider
    if provider:
        defaults = {
            "gemini": "gemini-3-flash-preview",
            "anthropic": "claude-3-haiku-20240307",
            "openai": "gpt-3.5-turbo",
            "groq": "mixtral-8x7b-32768",
            "cerebras": "llama3.1-8b",
            "deepseek": "deepseek-chat",
            "mistral": "mistral-small-latest",
        }
        default_model = defaults.get(provider, "gpt-3.5-turbo")
        logger.info(f"Using default model {default_model} for provider {provider}")
        
        # Format correctly based on provider
        if provider == "gemini":
            return default_model
        return f"{provider}/{default_model}"
    
    # Try to detect from environment variables
    if os.environ.get("GEMINI_API_KEY"):
        logger.info("Detected GEMINI_API_KEY, using Gemini")
        return "gemini-3-flash-preview"
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("Detected ANTHROPIC_API_KEY, using Claude")
        return "anthropic/claude-3-haiku-20240307"
    if os.environ.get("OPENAI_API_KEY"):
        logger.info("Detected OPENAI_API_KEY, using OpenAI")
        return "openai/gpt-3.5-turbo"
    if os.environ.get("GROQ_API_KEY"):
        logger.info("Detected GROQ_API_KEY, using Groq")
        return "groq/mixtral-8x7b-32768"
    if os.environ.get("CEREBRAS_API_KEY"):
        logger.info("Detected CEREBRAS_API_KEY, using Cerebras")
        return "cerebras/llama3.1-8b"
    
    # Last resort - warn and return Gemini (free tier available)
    logger.warning(
        "No LLM provider configured. Defaulting to Gemini (free tier). "
        "Run ./quickstart.sh to configure your preferred provider."
    )
    return "gemini-3-flash-preview"


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


def get_api_key(provider: str | None = None) -> str | None:
    """Return the API key for the configured or specified provider.
    
    Args:
        provider: Optional provider name to get key for. If None, uses configured provider.
    
    Returns:
        API key string or None if not found
    """
    llm = get_hive_config().get("llm", {})
    
    # If provider specified, get key for that provider
    if provider:
        provider = provider.lower()
        # Provider-specific environment variable mapping
        env_var_map = {
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "mistral": "MISTRAL_API_KEY",
        }
        if provider in env_var_map:
            return os.environ.get(env_var_map[provider])
        return None
    
    # Otherwise use configured provider
    configured_provider = llm.get("provider", "").lower()

    # Provider-specific environment variable mapping
    env_var_map = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mistral": "MISTRAL_API_KEY",
    }

    # 1. Check subscription modes first
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                logger.debug("Using Claude Code subscription token")
                return token
        except ImportError:
            pass

    if llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                logger.debug("Using Codex subscription token")
                return token
        except ImportError:
            pass

    # 2. Check provider-specific environment variable
    if configured_provider in env_var_map:
        env_var = env_var_map[configured_provider]
        api_key = os.environ.get(env_var)
        if api_key:
            logger.debug(f"Using {env_var} from environment")
            return api_key

    # 3. Fall back to generic env var from config
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        api_key = os.environ.get(api_key_env_var)
        if api_key:
            logger.debug(f"Using {api_key_env_var} from environment")
            return api_key

    logger.debug(f"No API key found for provider: {configured_provider}")
    return None


def get_gcu_enabled() -> bool:
    """Return whether GCU (browser automation) is enabled in user config."""
    return get_hive_config().get("gcu_enabled", True)


def get_api_base() -> str | None:
    """Return the api_base URL for OpenAI-compatible endpoints, if configured."""
    llm = get_hive_config().get("llm", {})
    
    # Special endpoints for subscription modes
    if llm.get("use_codex_subscription"):
        return "https://chatgpt.com/backend-api/codex"
    
    # Provider-specific API bases
    provider = llm.get("provider", "").lower()
    if provider == "minimax":
        return "https://api.minimax.io/v1"
    
    # Custom API base from config
    return llm.get("api_base")


def get_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider.
    
    Handles special cases for subscription modes:
    - Claude Code subscription: Adds OAuth Bearer token headers
    - Codex subscription: Adds ChatGPT-specific headers
    
    Returns:
        Dict of extra kwargs to pass to LiteLLMProvider
    """
    llm = get_hive_config().get("llm", {})
    extra_kwargs = {}
    
    # Claude Code subscription headers
    if llm.get("use_claude_code_subscription"):
        api_key = get_api_key()
        if api_key:
            extra_kwargs["extra_headers"] = {
                "authorization": f"Bearer {api_key}"
            }
            logger.debug("Added Claude Code OAuth headers")
    
    # Codex subscription headers
    if llm.get("use_codex_subscription"):
        api_key = get_api_key()
        if api_key:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CodexBar",
            }
            try:
                from framework.runner.runner import get_codex_account_id
                account_id = get_codex_account_id()
                if account_id:
                    headers["ChatGPT-Account-Id"] = account_id
                    logger.debug(f"Added ChatGPT-Account-Id: {account_id}")
            except ImportError:
                pass
            
            extra_kwargs["extra_headers"] = headers
            extra_kwargs["store"] = False
            extra_kwargs["allowed_openai_params"] = ["store"]
            logger.debug("Added Codex subscription headers")
    
    return extra_kwargs


def save_provider_selection(provider: str, model: str, api_key: str | None = None):
    """Save the user's provider selection to config."""
    config = get_hive_config()
    if "llm" not in config:
        config["llm"] = {}
    
    config["llm"]["provider"] = provider
    config["llm"]["model"] = model
    
    # Save to file
    with open(HIVE_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    
    logger.info(f" Saved provider selection: {provider} with model {model}")


# ---------------------------------------------------------------------------
# RuntimeConfig – shared across agent templates
# ---------------------------------------------------------------------------


@dataclass
class RuntimeConfig:
    """Agent runtime configuration loaded from ~/.hive/configuration.json."""
    
    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)
    
    def __post_init__(self):
        """Log the configuration after initialization."""
        logger.debug(f"RuntimeConfig initialized with model: {self.model}")
        if self.api_base:
            logger.debug(f"Using API base: {self.api_base}")


# ---------------------------------------------------------------------------
# Debugging helpers
# ---------------------------------------------------------------------------


def debug_llm_config() -> dict[str, Any]:
    """Print current LLM configuration for debugging.
    
    Returns:
        Dict with current LLM configuration status
    """
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "not set")
    model = config.get("model", "not set")
    
    # Check environment variables
    env_status = {
        "GEMINI_API_KEY": "✓" if os.environ.get("GEMINI_API_KEY") else "✗",
        "ANTHROPIC_API_KEY": "✓" if os.environ.get("ANTHROPIC_API_KEY") else "✗",
        "OPENAI_API_KEY": "✓" if os.environ.get("OPENAI_API_KEY") else "✗",
        "GROQ_API_KEY": "✓" if os.environ.get("GROQ_API_KEY") else "✗",
        "CEREBRAS_API_KEY": "✓" if os.environ.get("CEREBRAS_API_KEY") else "✗",
        "DEEPSEEK_API_KEY": "✓" if os.environ.get("DEEPSEEK_API_KEY") else "✗",
        "MISTRAL_API_KEY": "✓" if os.environ.get("MISTRAL_API_KEY") else "✗",
    }
    
    # Get the actual model that will be used
    preferred_model = get_preferred_model()
    api_key = get_api_key()
    
    debug_info = {
        "configured_provider": provider,
        "configured_model": model,
        "effective_model": preferred_model,
        "api_key_found": bool(api_key),
        "api_base": get_api_base(),
        "environment_variables": env_status,
        "subscription_mode": {
            "claude_code": config.get("use_claude_code_subscription", False),
            "codex": config.get("use_codex_subscription", False),
        },
        "available_providers": list(get_available_providers().keys())
    }
    
    # Log the configuration
    logger.info(" LLM Configuration Debug:")
    logger.info(json.dumps(debug_info, indent=2))
    
    return debug_info


def validate_llm_config() -> tuple[bool, list[str]]:
    """Validate that the LLM configuration is complete and correct.
    
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model = config.get("model", "")
    
    # Check if provider is set
    if not provider:
        issues.append("No LLM provider configured. Run ./quickstart.sh")
    
    # Check if model is set
    if not model and provider:
        issues.append(f"Provider '{provider}' has no model configured")
    
    # Check API key for non-subscription modes
    if not config.get("use_claude_code_subscription") and not config.get("use_codex_subscription"):
        api_key = get_api_key()
        if not api_key:
            issues.append(f"No API key found for provider '{provider}'")
    
    # Provider-specific checks
    if provider == "gemini":
        if not os.environ.get("GEMINI_API_KEY") and not get_api_key():
            issues.append("Gemini requires GEMINI_API_KEY environment variable")
    
    elif provider == "anthropic":
        api_key = get_api_key()
        if api_key and not (api_key.startswith("sk-ant-") or api_key.startswith("sk-ant-oat")):
            issues.append("Anthropic API key should start with 'sk-ant-'")
    
    is_valid = len(issues) == 0
    if is_valid:
        logger.info(" LLM configuration is valid")
    else:
        logger.warning(" LLM configuration has issues:")
        for issue in issues:
            logger.warning(f"  • {issue}")
    
    return is_valid, issues
