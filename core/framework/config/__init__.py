"""Configuration management for Hive.

This module provides configuration utilities and data structures for managing
Hive settings, particularly LLM model and provider configurations.
"""

from __future__ import annotations

from framework.config.model_providers import (
    PROVIDERS,
    ModelInfo,
    ProviderInfo,
    get_model_info,
    get_provider_by_id,
    get_provider_for_model,
    validate_model_provider_match,
)

__all__ = [
    "PROVIDERS",
    "ModelInfo",
    "ProviderInfo",
    "get_model_info",
    "get_provider_by_id",
    "get_provider_for_model",
    "validate_model_provider_match",
]
