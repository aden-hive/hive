"""Pipeline stage registry -- maps type names to stage classes.

Stages self-register via the ``@register`` decorator. The
``build_pipeline_from_config`` function reads a declarative config
(from ``~/.hive/configuration.json`` or ``agent.json``) and
instantiates the corresponding stage objects.

Example config::

    {
      "pipeline": {
        "stages": [
          {"type": "rate_limit", "order": 200, "config": {"max_requests_per_minute": 60}},
          {"type": "cost_guard", "order": 300, "config": {"max_cost_per_request": 0.50}}
        ]
      }
    }
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from framework.pipeline.runner import PipelineRunner
from framework.pipeline.stage import PipelineStage

logger = logging.getLogger(__name__)

_STAGE_REGISTRY: dict[str, type[PipelineStage]] = {}

# Tracks whether the built-in stage modules have been imported. Kept
# separate from ``_STAGE_REGISTRY`` because a user-defined stage can also
# populate the registry before the built-ins are imported, which previously
# caused ``_ensure_builtins_registered`` to skip importing the built-ins.
_BUILTINS_REGISTERED = False


def register(name: str):
    """Decorator to register a pipeline stage class by type name.

    Usage::

        @register("rate_limit")
        class RateLimitStage(PipelineStage):
            ...
    """

    def decorator(cls: type[PipelineStage]) -> type[PipelineStage]:
        _STAGE_REGISTRY[name] = cls
        return cls

    return decorator


def get_registered_stages() -> dict[str, type[PipelineStage]]:
    """Return a copy of the stage registry."""
    return dict(_STAGE_REGISTRY)


def build_stage(spec: dict[str, Any]) -> PipelineStage:
    """Instantiate a single stage from a config spec.

    Args:
        spec: Dict with ``type`` (required), ``order`` (optional),
              and ``config`` (optional kwargs dict).

    Raises:
        KeyError: If the stage type is not registered.
    """
    stage_type = spec["type"]
    if stage_type not in _STAGE_REGISTRY:
        available = ", ".join(sorted(_STAGE_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown pipeline stage type '{stage_type}'. Available: {available}")
    cls = _STAGE_REGISTRY[stage_type]
    config = spec.get("config", {})
    stage = cls(**config)
    if "order" in spec:
        stage.order = spec["order"]
    return stage


def build_pipeline_from_config(
    stages_config: list[dict[str, Any]],
) -> PipelineRunner:
    """Build a ``PipelineRunner`` from a declarative stages list.

    Each entry is ``{"type": "...", "order": N, "config": {...}}``.
    """
    # Import built-in stages so they self-register
    _ensure_builtins_registered()

    stages = [build_stage(s) for s in stages_config]
    return PipelineRunner(stages)


def _ensure_builtins_registered() -> None:
    """Import built-in stage modules so their ``@register`` decorators fire."""
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    # Import built-ins one at a time so a failure in one module does not
    # silently prevent the remaining built-ins from registering.
    builtin_modules = (
        "framework.pipeline.stages.cost_guard",
        "framework.pipeline.stages.credential_resolver",
        "framework.pipeline.stages.input_validation",
        "framework.pipeline.stages.llm_provider",
        "framework.pipeline.stages.mcp_registry",
        "framework.pipeline.stages.rate_limit",
        "framework.pipeline.stages.skill_registry",
    )
    for module in builtin_modules:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            logger.warning(
                "Failed to import built-in pipeline stage %r: %s", module, exc
            )
    _BUILTINS_REGISTERED = True
