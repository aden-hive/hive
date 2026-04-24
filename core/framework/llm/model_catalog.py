"""Shared curated model metadata loaded from ``model_catalog.json``."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_CATALOG_PATH = Path(__file__).with_name("model_catalog.json")


class ModelCatalogError(RuntimeError):
    """Raised when the curated model catalogue is missing or malformed."""


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelCatalogError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ModelCatalogError(f"{path} must be an array")
    return value


_PRICING_KEYS = ("input", "output", "cache_read", "cache_creation")


def _validate_pricing(value: Any, path: str) -> None:
    """Validate an optional ``pricing_usd_per_mtok`` block.

    Keys are USD-per-million-tokens rates. ``input``/``output`` are required;
    ``cache_read``/``cache_creation`` are optional. All values must be
    non-negative numbers. Used as a last-resort fallback when neither the
    provider nor LiteLLM's catalog reports a cost.
    """
    pricing = _require_mapping(value, path)
    for key in ("input", "output"):
        if key not in pricing:
            raise ModelCatalogError(f"{path}.{key} is required")
    for key, rate in pricing.items():
        if key not in _PRICING_KEYS:
            raise ModelCatalogError(f"{path}.{key} is not a recognized pricing field")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate < 0:
            raise ModelCatalogError(f"{path}.{key} must be a non-negative number")


def _validate_model_catalog(data: dict[str, Any]) -> dict[str, Any]:
    providers = _require_mapping(data.get("providers"), "providers")

    for provider_id, provider_info in providers.items():
        provider_path = f"providers.{provider_id}"
        provider_map = _require_mapping(provider_info, provider_path)
        default_model = provider_map.get("default_model")
        if not isinstance(default_model, str) or not default_model.strip():
            raise ModelCatalogError(f"{provider_path}.default_model must be a non-empty string")

        models = _require_list(provider_map.get("models"), f"{provider_path}.models")
        if not models:
            raise ModelCatalogError(f"{provider_path}.models must not be empty")

        seen_model_ids: set[str] = set()
        default_found = False
        for idx, model in enumerate(models):
            model_path = f"{provider_path}.models[{idx}]"
            model_map = _require_mapping(model, model_path)
            model_id = model_map.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                raise ModelCatalogError(f"{model_path}.id must be a non-empty string")
            if model_id in seen_model_ids:
                raise ModelCatalogError(f"Duplicate model id {model_id!r} in {provider_path}.models")
            seen_model_ids.add(model_id)

            if model_id == default_model:
                default_found = True

            label = model_map.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ModelCatalogError(f"{model_path}.label must be a non-empty string")

            recommended = model_map.get("recommended")
            if not isinstance(recommended, bool):
                raise ModelCatalogError(f"{model_path}.recommended must be a boolean")

            for key in ("max_tokens", "max_context_tokens"):
                value = model_map.get(key)
                if not isinstance(value, int) or value <= 0:
                    raise ModelCatalogError(f"{model_path}.{key} must be a positive integer")

            pricing = model_map.get("pricing_usd_per_mtok")
            if pricing is not None:
                _validate_pricing(pricing, f"{model_path}.pricing_usd_per_mtok")

        if not default_found:
            raise ModelCatalogError(
                f"{provider_path}.default_model={default_model!r} is not present in {provider_path}.models"
            )

    presets = _require_mapping(data.get("presets"), "presets")
    for preset_id, preset_info in presets.items():
        preset_path = f"presets.{preset_id}"
        preset_map = _require_mapping(preset_info, preset_path)

        provider = preset_map.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ModelCatalogError(f"{preset_path}.provider must be a non-empty string")

        model = preset_map.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ModelCatalogError(f"{preset_path}.model must be a non-empty string when present")

        api_base = preset_map.get("api_base")
        if api_base is not None and (not isinstance(api_base, str) or not api_base.strip()):
            raise ModelCatalogError(f"{preset_path}.api_base must be a non-empty string when present")

        api_key_env_var = preset_map.get("api_key_env_var")
        if api_key_env_var is not None and (not isinstance(api_key_env_var, str) or not api_key_env_var.strip()):
            raise ModelCatalogError(f"{preset_path}.api_key_env_var must be a non-empty string when present")

        for key in ("max_tokens", "max_context_tokens"):
            value = preset_map.get(key)
            if not isinstance(value, int) or value <= 0:
                raise ModelCatalogError(f"{preset_path}.{key} must be a positive integer")

        model_choices = preset_map.get("model_choices")
        if model_choices is not None:
            for idx, choice in enumerate(_require_list(model_choices, f"{preset_path}.model_choices")):
                choice_path = f"{preset_path}.model_choices[{idx}]"
                choice_map = _require_mapping(choice, choice_path)
                choice_id = choice_map.get("id")
                if not isinstance(choice_id, str) or not choice_id.strip():
                    raise ModelCatalogError(f"{choice_path}.id must be a non-empty string")
                label = choice_map.get("label")
                if not isinstance(label, str) or not label.strip():
                    raise ModelCatalogError(f"{choice_path}.label must be a non-empty string")
                recommended = choice_map.get("recommended")
                if not isinstance(recommended, bool):
                    raise ModelCatalogError(f"{choice_path}.recommended must be a boolean")

    return data


@lru_cache(maxsize=1)
def load_model_catalog() -> dict[str, Any]:
    """Load and validate the curated model catalogue."""
    try:
        raw = json.loads(MODEL_CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelCatalogError(f"Model catalogue not found: {MODEL_CATALOG_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ModelCatalogError(f"Model catalogue JSON is invalid: {exc}") from exc

    return _validate_model_catalog(_require_mapping(raw, "root"))


def get_models_catalogue() -> dict[str, list[dict[str, Any]]]:
    """Return provider -> model list."""
    providers = load_model_catalog()["providers"]
    return {provider_id: copy.deepcopy(provider_info["models"]) for provider_id, provider_info in providers.items()}


def get_default_models() -> dict[str, str]:
    """Return provider -> default model id."""
    providers = load_model_catalog()["providers"]
    return {provider_id: str(provider_info["default_model"]) for provider_id, provider_info in providers.items()}


def get_provider_models(provider: str) -> list[dict[str, Any]]:
    """Return the curated models for one provider."""
    provider_info = load_model_catalog()["providers"].get(provider)
    if not provider_info:
        return []
    return copy.deepcopy(provider_info["models"])


def get_default_model(provider: str) -> str | None:
    """Return the curated default model id for one provider."""
    provider_info = load_model_catalog()["providers"].get(provider)
    if not provider_info:
        return None
    return str(provider_info["default_model"])


def find_model(provider: str, model_id: str) -> dict[str, Any] | None:
    """Return one model entry for a provider, if present."""
    for model in load_model_catalog()["providers"].get(provider, {}).get("models", []):
        if model["id"] == model_id:
            return copy.deepcopy(model)
    return None


def find_model_any_provider(model_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return the first curated provider/model entry matching a model id."""
    for provider_id, provider_info in load_model_catalog()["providers"].items():
        for model in provider_info["models"]:
            if model["id"] == model_id:
                return provider_id, copy.deepcopy(model)
    return None


def get_model_limits(provider: str, model_id: str) -> tuple[int, int] | None:
    """Return ``(max_tokens, max_context_tokens)`` for one provider/model pair."""
    model = find_model(provider, model_id)
    if not model:
        return None
    return int(model["max_tokens"]), int(model["max_context_tokens"])


def get_model_pricing(model_id: str) -> dict[str, float] | None:
    """Return ``pricing_usd_per_mtok`` for a model id, searching all providers.

    Returns ``None`` when the model is absent from the catalog or has no
    pricing entry. Used by the cost-extraction fallback in ``litellm.py``
    when the provider response and LiteLLM's catalog both come up empty.
    """
    if not model_id:
        return None
    for provider_info in load_model_catalog()["providers"].values():
        for model in provider_info["models"]:
            if model["id"] == model_id:
                pricing = model.get("pricing_usd_per_mtok")
                if pricing is None:
                    return None
                return {key: float(rate) for key, rate in pricing.items()}
    return None


def get_preset(preset_id: str) -> dict[str, Any] | None:
    """Return one preset entry."""
    preset = load_model_catalog()["presets"].get(preset_id)
    if not preset:
        return None
    return copy.deepcopy(preset)


def get_presets() -> dict[str, dict[str, Any]]:
    """Return all preset entries."""
    return copy.deepcopy(load_model_catalog()["presets"])
