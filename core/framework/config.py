"""Framework-wide configuration constants.

This module centralizes default values used across the framework to avoid
DRY violations and make configuration changes easier to maintain.
"""
import os

# Default LLM models
# These can be overridden via environment variables
DEFAULT_ROUTING_MODEL = os.getenv("DEFAULT_ROUTING_MODEL", "claude-haiku-4-5-20251001")
"""Default model for routing, orchestration, and general LLM tasks."""

DEFAULT_RUNNER_MODEL = os.getenv("DEFAULT_RUNNER_MODEL", "cerebras/zai-glm-4.7")
"""Default model for agent runner execution."""

# Alias for backward compatibility
DEFAULT_MODEL = DEFAULT_ROUTING_MODEL
"""Alias for DEFAULT_ROUTING_MODEL."""
