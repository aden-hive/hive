"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.graph.edge import DEFAULT_MAX_TOKENS
from framework.llm.provider_models import (
    get_model_capabilities,
    get_model_display_name,
    get_model_info,
)

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"

# Hive LLM router endpoint (Anthropic-compatible).
# litellm's Anthropic handler appends /v1/messages, so this is just the base host.
HIVE_LLM_ENDPOINT = "https://api.adenhq.com"
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
# Derived helpers
# ---------------------------------------------------------------------------


def get_preferred_model() -> str:
    """Return the user's preferred LLM model string (e.g. 'anthropic/claude-sonnet-4-20250514')."""
    llm = get_hive_config().get("llm", {})
    if llm.get("provider") and llm.get("model"):
        provider = str(llm["provider"])
        model = str(llm["model"]).strip()
        # OpenRouter quickstart stores raw model IDs; tolerate pasted "openrouter/<id>" too.
        if provider.lower() == "openrouter" and model.lower().startswith("openrouter/"):
            model = model[len("openrouter/") :]
        if model:
            return f"{provider}/{model}"
    return "anthropic/claude-sonnet-4-20250514"


def get_preferred_worker_model() -> str | None:
    """Return the user's preferred worker LLM model, or None if not configured.

    Reads from the ``worker_llm`` section of ~/.hive/configuration.json.
    Returns None when no worker-specific model is set, so callers can
    fall back to the default (queen) model via ``get_preferred_model()``.
    """
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm.get("provider") and worker_llm.get("model"):
        provider = str(worker_llm["provider"])
        model = str(worker_llm["model"]).strip()
        if provider.lower() == "openrouter" and model.lower().startswith("openrouter/"):
            model = model[len("openrouter/") :]
        if model:
            return f"{provider}/{model}"
    return None


def get_worker_api_key() -> str | None:
    """Return the API key for the worker LLM, falling back to the default key."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_api_key()

    # Worker-specific subscription / env var
    if worker_llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    if worker_llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    if worker_llm.get("use_kimi_code_subscription"):
        try:
            from framework.runner.runner import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    api_key_env_var = worker_llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)

    # Fall back to default key
    return get_api_key()


def get_worker_api_base() -> str | None:
    """Return the api_base for the worker LLM, falling back to the default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_api_base()

    if worker_llm.get("use_codex_subscription"):
        return "https://chatgpt.com/backend-api/codex"
    if worker_llm.get("use_kimi_code_subscription"):
        return "https://api.kimi.com/coding"
    if worker_llm.get("api_base"):
        return worker_llm["api_base"]
    if str(worker_llm.get("provider", "")).lower() == "openrouter":
        return OPENROUTER_API_BASE
    return None


def get_worker_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for the worker LLM provider."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_llm_extra_kwargs()

    if worker_llm.get("use_claude_code_subscription"):
        api_key = get_worker_api_key()
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }
    if worker_llm.get("use_codex_subscription"):
        api_key = get_worker_api_key()
        if api_key:
            headers: dict[str, str] = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CodexBar",
            }
            try:
                from framework.runner.runner import get_codex_account_id

                account_id = get_codex_account_id()
                if account_id:
                    headers["ChatGPT-Account-Id"] = account_id
            except ImportError:
                pass
            return {
                "extra_headers": headers,
                "store": False,
                "allowed_openai_params": ["store"],
            }
    return {}


def get_worker_max_tokens() -> int:
    """Return max_tokens for the worker LLM, falling back to default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm and "max_tokens" in worker_llm:
        return worker_llm["max_tokens"]
    return get_max_tokens()


def get_worker_max_context_tokens() -> int:
    """Return max_context_tokens for the worker LLM, falling back to default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm and "max_context_tokens" in worker_llm:
        return worker_llm["max_context_tokens"]
    return get_max_context_tokens()


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


DEFAULT_MAX_CONTEXT_TOKENS = 32_000
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def get_max_context_tokens() -> int:
    """Return the configured max_context_tokens, falling back to DEFAULT_MAX_CONTEXT_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)


def get_api_key(provider: str | None = None) -> str | None:
    """Return the API key, supporting env var, Claude Code subscription, Codex, and ZAI Code.

    Priority:
    1. Claude Code subscription (``use_claude_code_subscription: true``)
       reads the OAuth token from ``~/.claude/.credentials.json``.
    2. Codex subscription (``use_codex_subscription: true``)
       reads the OAuth token from macOS Keychain or ``~/.codex/auth.json``.
    3. Environment variable named in ``api_key_env_var``.
    4. Provider-specific env var based on configured or detected provider.
    """
    llm = get_hive_config().get("llm", {})
    explicit_provider = (provider or "").lower()
    configured_provider = str(llm.get("provider", "")).lower()
    effective_provider = explicit_provider or configured_provider

    # Claude Code subscription: read OAuth token directly
    if not explicit_provider and llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Codex subscription: read OAuth token from Keychain / auth.json
    if not explicit_provider and llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    # Kimi Code subscription: read API key from ~/.kimi/config.toml
    if not explicit_provider and llm.get("use_kimi_code_subscription"):
        try:
            from framework.runner.runner import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Standard env-var path (covers ZAI Code and all API-key providers)
    api_key_env_var = llm.get("api_key_env_var")
    if not explicit_provider and api_key_env_var:
        return os.environ.get(api_key_env_var)

    env_var_map = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",  # Add OpenRouter
        "groq": "GROQ_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }

    if effective_provider in env_var_map:
        env_var = env_var_map[effective_provider]
        api_key = os.environ.get(env_var)
        if api_key:
            logger.debug(f"Using {env_var} from environment")
            return api_key

    # If no provider was requested or configured, try to detect from environment
    if not effective_provider:
        for provider_name, env_var in env_var_map.items():
            api_key = os.environ.get(env_var)
            if api_key:
                logger.debug(f"Detected {provider_name} from {env_var}")
                return api_key

    logger.debug(f"No API key found for provider: {effective_provider or 'unknown'}")
    return None


def get_gcu_enabled() -> bool:
    """Return whether GCU (browser automation) is enabled in user config."""
    return get_hive_config().get("gcu_enabled", True)


def get_gcu_viewport_scale() -> float:
    """Return GCU viewport scale factor (0.1-1.0), default 0.8."""
    scale = get_hive_config().get("gcu_viewport_scale", 0.8)
    if isinstance(scale, (int, float)) and 0.1 <= scale <= 1.0:
        return float(scale)
    return 0.8


def get_api_base() -> str | None:
    """Return the api_base URL for OpenAI-compatible endpoints, if configured."""
    llm = get_hive_config().get("llm", {})
    if llm.get("use_codex_subscription"):
        # Codex subscription routes through the ChatGPT backend, not api.openai.com.
        return "https://chatgpt.com/backend-api/codex"
    if llm.get("use_kimi_code_subscription"):
        # Kimi Code uses an Anthropic-compatible endpoint (no /v1 suffix).
        return "https://api.kimi.com/coding"
    if llm.get("api_base"):
        return llm["api_base"]
    if str(llm.get("provider", "")).lower() == "openrouter":
        return OPENROUTER_API_BASE
    # Minimax needs a specific base URL
    if str(llm.get("provider", "")).lower() == "minimax":
        return "https://api.minimax.io/v1"
    return None


def get_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider (e.g. OAuth headers).

    When ``use_claude_code_subscription`` is enabled, returns
    ``extra_headers`` with the OAuth Bearer token so that litellm's
    built-in Anthropic OAuth handler adds the required beta headers.

    When ``use_codex_subscription`` is enabled, returns
    ``extra_headers`` with the Bearer token, ``ChatGPT-Account-Id``,
    and ``store=False`` (required by the ChatGPT backend).
    """
    llm = get_hive_config().get("llm", {})
    if llm.get("use_claude_code_subscription"):
        api_key = get_api_key()
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }
    if llm.get("use_codex_subscription"):
        api_key = get_api_key()
        if api_key:
            headers: dict[str, str] = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CodexBar",
            }
            try:
                from framework.runner.runner import get_codex_account_id

                account_id = get_codex_account_id()
                if account_id:
                    headers["ChatGPT-Account-Id"] = account_id
            except ImportError:
                pass
            return {
                "extra_headers": headers,
                "store": False,
                "allowed_openai_params": ["store"],
            }
    return {}


def get_available_providers() -> dict[str, dict[str, Any]]:
    """Get all available LLM providers based on environment variables."""
    available = {}

    # Gemini
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

    # Anthropic
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        available["anthropic"] = {
            "name": "Anthropic Claude",
            "api_key": anthropic_key,
            "status": "needs_check",
            "models": [
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-3-5-sonnet-20240620"
            ],
            "default_model": "claude-3-haiku-20240307",
            "free_tier": False
        }

    # OpenAI
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

    # OpenRouter
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        available["openrouter"] = {
            "name": "OpenRouter",
            "api_key": openrouter_key,
            "api_base": OPENROUTER_API_BASE,
            "status": "needs_check",
            "models": ["openrouter/anthropic/claude-3.5-sonnet", "openrouter/openai/gpt-4o"],
            "default_model": "openrouter/anthropic/claude-3.5-sonnet",
            "free_tier": False
        }

    # Groq
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        available["groq"] = {
            "name": "Groq",
            "api_key": groq_key,
            "status": "available",
            "models": ["mixtral-8x7b-32768", "llama3-70b-8192", "llama3-8b-8192"],
            "default_model": "mixtral-8x7b-32768",
            "free_tier": True
        }

    # Cerebras
    cerebras_key = os.environ.get("CEREBRAS_API_KEY")
    if cerebras_key:
        available["cerebras"] = {
            "name": "Cerebras",
            "api_key": cerebras_key,
            "status": "available",
            "models": ["llama3.1-8b", "llama3.1-70b"],
            "default_model": "llama3.1-8b",
            "free_tier": True
        }

    # DeepSeek
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

    # Mistral
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

    # Minimax
    minimax_key = os.environ.get("MINIMAX_API_KEY")
    if minimax_key:
        available["minimax"] = {
            "name": "Minimax",
            "api_key": minimax_key,
            "api_base": "https://api.minimax.io/v1",
            "status": "needs_check",
            "models": ["MiniMax-Text-01", "abab6.5-chat"],
            "default_model": "MiniMax-Text-01",
            "free_tier": False
        }

    return available


def format_provider_menu(providers: dict) -> str:
    """Format provider menu for interactive selection."""
    if not providers:
        return "No providers available. Please configure API keys."
    menu = "\nAvailable LLM Providers:\n"
    menu += "-" * 50 + "\n"
    for idx, (provider_id, info) in enumerate(providers.items(), 1):
        free_tag = " (Free Tier)" if info.get("free_tier") else ""
        status_icon = "✓" if info["status"] == "available" else "?"
        menu += f"\n{idx}. {status_icon} {info['name']}{free_tag}"
        menu += f"\n   Models: {', '.join(info['models'][:3])}"
        if len(info['models']) > 3:
            menu += f" and {len(info['models'])-3} more"
        if info["status"] == "needs_check":
            menu += "\n   Note: Will verify credits when used"
        menu += "\n"
    menu += "\n" + "-" * 50
    menu += "\n0. Keep using current selection and show error"
    return menu


def get_provider_from_env() -> str | None:
    """Detect provider from environment variables."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("CEREBRAS_API_KEY"):
        return "cerebras"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.environ.get("MISTRAL_API_KEY"):
        return "mistral"
    if os.environ.get("MINIMAX_API_KEY"):
        return "minimax"
    return None


def save_provider_selection(provider: str, model: str, api_key: str | None = None) -> None:
    """Save provider selection to configuration file."""
    # Ensure directory exists before writing
    HIVE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    config = get_hive_config()
    llm = config.setdefault("llm", {})

    # Clear stale auth/backend overrides when saving a new provider
    for key in (
        "use_claude_code_subscription",
        "use_codex_subscription",
        "use_kimi_code_subscription",
        "api_key_env_var",
        "api_base",
    ):
        llm.pop(key, None)

    llm["provider"] = provider
    llm["model"] = model

    try:
        with open(HIVE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Saved provider selection: {provider} with model {model}")
    except Exception as e:
        logger.error(f"Failed to save provider selection: {e}")


def get_provider_from_config() -> str:
    """Get the configured provider."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    # If it's empty, try to detect from environment
    if not provider:
        return get_provider_from_env() or ""
    return provider


def get_model_api_name_from_config() -> str:
    """Get the API model name from config."""
    config = get_hive_config().get("llm", {})
    return config.get("model", "")


def get_model_display_name_from_config() -> str:
    """Get the user-friendly model display name from config."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model_api_name = config.get("model", "")

    if provider and model_api_name:
        return get_model_display_name(provider, model_api_name)
    return model_api_name or "Unknown"


def get_model_capabilities_from_config() -> dict[str, bool]:
    """Get model capabilities from config."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model = config.get("model", "")

    if provider and model:
        return get_model_capabilities(provider, model)

    # Default capabilities
    return {
        "streaming": True,
        "tools": True,
        "json_mode": True
    }


def get_model_max_tokens() -> int:
    """Get the max tokens for the configured model."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model = config.get("model", "")

    if provider and model:
        model_info = get_model_info(provider, model)
        if model_info:
            return model_info["max_tokens"]

    # Fall back to configured max_tokens or default
    return config.get("max_tokens", DEFAULT_MAX_TOKENS)


def format_model_info_for_display() -> str:
    """Format model information for display in UI."""
    provider = get_provider_from_config()
    model_api = get_model_api_name_from_config()
    model_display = get_model_display_name_from_config()

    if not provider or not model_api:
        return "No model configured"

    model_info = get_model_info(provider, model_api)
    if model_info:
        tier_icon = "🆓" if model_info["tier"] == "free" else "💰"
        return f"{provider.title()}: {model_display} {tier_icon}"

    return f"{provider.title()}: {model_api}"


def save_config(config: dict) -> bool:
    """Save configuration to ~/.hive/configuration.json."""
    try:
        # Ensure directory exists
        HIVE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(HIVE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Configuration saved to {HIVE_CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def debug_llm_config() -> dict[str, Any]:
    """Debug LLM configuration for troubleshooting."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "not set")
    model = config.get("model", "not set")
    env_status = {
        "GEMINI_API_KEY": "✓" if os.environ.get("GEMINI_API_KEY") else "✗",
        "ANTHROPIC_API_KEY": "✓" if os.environ.get("ANTHROPIC_API_KEY") else "✗",
        "OPENAI_API_KEY": "✓" if os.environ.get("OPENAI_API_KEY") else "✗",
        "OPENROUTER_API_KEY": "✓" if os.environ.get("OPENROUTER_API_KEY") else "✗",
        "GROQ_API_KEY": "✓" if os.environ.get("GROQ_API_KEY") else "✗",
        "CEREBRAS_API_KEY": "✓" if os.environ.get("CEREBRAS_API_KEY") else "✗",
        "DEEPSEEK_API_KEY": "✓" if os.environ.get("DEEPSEEK_API_KEY") else "✗",
        "MISTRAL_API_KEY": "✓" if os.environ.get("MISTRAL_API_KEY") else "✗",
        "MINIMAX_API_KEY": "✓" if os.environ.get("MINIMAX_API_KEY") else "✗",
    }
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
    logger.info("LLM Configuration Debug:")
    logger.info(json.dumps(debug_info, indent=2))
    return debug_info


def validate_llm_config() -> tuple[bool, list[str]]:
    """Validate LLM configuration and return issues."""
    issues = []
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model = config.get("model", "")
    if not provider:
        issues.append("No LLM provider configured. Run ./quickstart.sh")
    if not model and provider:
        issues.append(f"Provider '{provider}' has no model configured")
    if not config.get("use_claude_code_subscription") and not config.get("use_codex_subscription"):
        api_key = get_api_key()
        if not api_key:
            issues.append(f"No API key found for provider '{provider}'")
    if provider == "gemini":
        if not os.environ.get("GEMINI_API_KEY") and not get_api_key():
            issues.append("Gemini requires GEMINI_API_KEY environment variable")
    elif provider == "anthropic":
        api_key = get_api_key()
        if api_key and not (api_key.startswith("sk-ant-") or api_key.startswith("sk-ant-oat")):
            issues.append("Anthropic API key should start with 'sk-ant-'")
    elif provider == "minimax":
        if not os.environ.get("MINIMAX_API_KEY") and not get_api_key():
            issues.append("Minimax requires MINIMAX_API_KEY environment variable")
    elif provider == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY") and not get_api_key():
            issues.append("OpenRouter requires OPENROUTER_API_KEY environment variable")

    is_valid = len(issues) == 0
    if is_valid:
        logger.info("LLM configuration is valid")
    else:
        logger.warning("LLM configuration has issues:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    return is_valid, issues


# ---------------------------------------------------------------------------
# RuntimeConfig – shared across agent templates
# ---------------------------------------------------------------------------


@dataclass
class RuntimeConfig:
    """Agent runtime configuration loaded from ~/.hive/configuration.json."""

    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    max_context_tokens: int = field(default_factory=get_max_context_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)

    def __post_init__(self):
        logger.debug(f"RuntimeConfig initialized with model: {self.model}")
        if self.api_base:
            logger.debug(f"Using API base: {self.api_base}")
