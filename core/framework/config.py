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
from typing import Any, Dict
from framework.llm.provider_models import get_model_display_name, get_model_info
from framework.graph.edge import DEFAULT_MAX_TOKENS
from framework.llm.provider_models import get_model_capabilities

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


def get_api_key() -> str | None:
    """Return the API key, supporting env var, Claude Code subscription, Codex, and ZAI Code.

    Priority:
    1. Claude Code subscription (``use_claude_code_subscription: true``)
       reads the OAuth token from ``~/.claude/.credentials.json``.
    2. Codex subscription (``use_codex_subscription: true``)
       reads the OAuth token from macOS Keychain or ``~/.codex/auth.json``.
    3. Environment variable named in ``api_key_env_var``.
    """
    llm = get_hive_config().get("llm", {})

    # Claude Code subscription: read OAuth token directly
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Codex subscription: read OAuth token from Keychain / auth.json
    if llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    # Kimi Code subscription: read API key from ~/.kimi/config.toml
    if llm.get("use_kimi_code_subscription"):
        try:
            from framework.runner.runner import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Standard env-var path (covers ZAI Code and all API-key providers)
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)
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
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from framework.graph.edge import DEFAULT_MAX_TOKENS

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"
logger = logging.getLogger(__name__)

def get_hive_config() -> dict[str, Any]:
    if not HIVE_CONFIG_FILE.exists():
        return {}
    try:
        with open(HIVE_CONFIG_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load Hive config %s: %s", HIVE_CONFIG_FILE, e)
        return {}

def get_available_providers() -> dict[str, dict[str, Any]]:
    available = {}
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
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("CEREBRAS_API_KEY"):
        return "cerebras"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.environ.get("MISTRAL_API_KEY"):
        return "mistral"
    return None

def save_provider_selection(provider: str, model: str, api_key: str | None = None) -> None:
    config = get_hive_config()
    if "llm" not in config:
        config["llm"] = {}
    config["llm"]["provider"] = provider
    config["llm"]["model"] = model
    try:
        with open(HIVE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Saved provider selection: {provider} with model {model}")
    except Exception as e:
        logger.error(f"Failed to save provider selection: {e}")

def get_preferred_model() -> str:
    llm = get_hive_config().get("llm", {})
    provider = llm.get("provider", "").lower()
    model = llm.get("model", "")
    if provider and model:
        if provider == "gemini":
            logger.debug(f"Using Gemini model: {model}")
            return model
        logger.debug(f"Using {provider} model: {provider}/{model}")
        return f"{provider}/{model}"
    if model:
        logger.debug(f"Using model from config: {model}")
        return model
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
        if provider == "gemini":
            return default_model
        return f"{provider}/{default_model}"
    env_provider = get_provider_from_env()
    if env_provider:
        defaults = {
            "gemini": "gemini-3-flash-preview",
            "anthropic": "claude-3-haiku-20240307",
            "openai": "gpt-3.5-turbo",
            "groq": "mixtral-8x7b-32768",
            "cerebras": "llama3.1-8b",
        }
        default_model = defaults.get(env_provider, "gpt-3.5-turbo")
        logger.info(f"Detected {env_provider} from environment, using {default_model}")
        if env_provider == "gemini":
            return default_model
        return f"{env_provider}/{default_model}"
    logger.warning("No LLM provider configured. Defaulting to Gemini (free tier). Run ./quickstart.sh to configure your preferred provider.")
    return "gemini-3-flash-preview"

def get_max_tokens() -> int:
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)

def get_api_key(provider: str | None = None) -> str | None:
    llm = get_hive_config().get("llm", {})
    env_var_map = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "mistral": "MISTRAL_API_KEY",
    }
    if provider:
        provider = provider.lower()
        if provider in env_var_map:
            return os.environ.get(env_var_map[provider])
        return None
    configured_provider = llm.get("provider", "").lower()
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token
            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass
    if llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token
            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass
    if configured_provider in env_var_map:
        env_var = env_var_map[configured_provider]
        api_key = os.environ.get(env_var)
        if api_key:
            logger.debug(f"Using {env_var} from environment")
            return api_key
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        api_key = os.environ.get(api_key_env_var)
        if api_key:
            logger.debug(f"Using {api_key_env_var} from environment")
            return api_key
    logger.debug(f"No API key found for provider: {configured_provider}")
    return None

def get_gcu_enabled() -> bool:
    return get_hive_config().get("gcu_enabled", True)

def get_api_base() -> str | None:
    llm = get_hive_config().get("llm", {})
    if llm.get("use_codex_subscription"):
        return "https://chatgpt.com/backend-api/codex"
    provider = llm.get("provider", "").lower()
    if provider == "minimax":
        return "https://api.minimax.io/v1"
    return llm.get("api_base")

def get_llm_extra_kwargs() -> dict[str, Any]:
    llm = get_hive_config().get("llm", {})
    extra_kwargs = {}
    if llm.get("use_claude_code_subscription"):
        api_key = get_api_key()
        if api_key:
            extra_kwargs["extra_headers"] = {"authorization": f"Bearer {api_key}"}
            logger.debug("Added Claude Code OAuth headers")
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

@dataclass
class RuntimeConfig:
    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)
    
    def __post_init__(self):
        logger.debug(f"RuntimeConfig initialized with model: {self.model}")
        if self.api_base:
            logger.debug(f"Using API base: {self.api_base}")

def debug_llm_config() -> dict[str, Any]:
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "not set")
    model = config.get("model", "not set")
    env_status = {
        "GEMINI_API_KEY": "✓" if os.environ.get("GEMINI_API_KEY") else "✗",
        "ANTHROPIC_API_KEY": "✓" if os.environ.get("ANTHROPIC_API_KEY") else "✗",
        "OPENAI_API_KEY": "✓" if os.environ.get("OPENAI_API_KEY") else "✗",
        "GROQ_API_KEY": "✓" if os.environ.get("GROQ_API_KEY") else "✗",
        "CEREBRAS_API_KEY": "✓" if os.environ.get("CEREBRAS_API_KEY") else "✗",
        "DEEPSEEK_API_KEY": "✓" if os.environ.get("DEEPSEEK_API_KEY") else "✗",
        "MISTRAL_API_KEY": "✓" if os.environ.get("MISTRAL_API_KEY") else "✗",
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
    is_valid = len(issues) == 0
    if is_valid:
        logger.info("LLM configuration is valid")
    else:
        logger.warning("LLM configuration has issues:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    return is_valid, issues
def get_model_display_name_from_config() -> str:
    """Get the user-friendly model display name from config."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    model_api_name = config.get("model", "")
    
    if provider and model_api_name:
        return get_model_display_name(provider, model_api_name)
    return model_api_name or "Unknown"

def get_model_api_name_from_config() -> str:
    """Get the API model name from config."""
    config = get_hive_config().get("llm", {})
    return config.get("model", "")

def get_model_capabilities_from_config() -> Dict[str, bool]:
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

def get_provider_from_config() -> str:
    """Get the configured provider."""
    config = get_hive_config().get("llm", {})
    provider = config.get("provider", "")
    # If it's empty, try to detect from environment
    if not provider:
        if os.environ.get("GEMINI_API_KEY"):
            return "gemini"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
    return provider

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
        with open(HIVE_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Configuration saved to {HIVE_CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False