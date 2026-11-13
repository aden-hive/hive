"""Tests for the pipeline stage registry.

Covers the fix for the bug where registering a custom stage before the
built-in stage modules are imported prevented ``build_pipeline_from_config``
from ever loading the built-ins (rate_limit, cost_guard, ...).
"""

from __future__ import annotations

import importlib
import sys

import pytest

from framework.pipeline import registry as registry_module
from framework.pipeline.registry import (
    build_pipeline_from_config,
    register,
)
from framework.pipeline.stage import PipelineResult, PipelineStage

pytestmark = pytest.mark.asyncio

_BUILTIN_MODULES = (
    "framework.pipeline.stages.cost_guard",
    "framework.pipeline.stages.credential_resolver",
    "framework.pipeline.stages.input_validation",
    "framework.pipeline.stages.llm_provider",
    "framework.pipeline.stages.mcp_registry",
    "framework.pipeline.stages.rate_limit",
    "framework.pipeline.stages.skill_registry",
)


@register("my_stage")
class MyStage(PipelineStage):
    order = 500

    async def process(self, ctx):
        return PipelineResult()


def _simulate_fresh_process():
    """Clear the registry and drop built-in modules so they re-import like a fresh process."""
    registry_module._STAGE_REGISTRY.clear()
    registry_module._BUILTINS_REGISTERED = False
    for module in _BUILTIN_MODULES:
        sys.modules.pop(module, None)
    # Re-register the custom stage (its decorator only fired at import time).
    registry_module._STAGE_REGISTRY["my_stage"] = MyStage


@pytest.fixture(autouse=True)
def _reset_registry():
    _simulate_fresh_process()
    yield
    _simulate_fresh_process()


async def test_builtins_load_after_custom_stage_registered():
    """Registering a custom stage first must not hide the built-in stages."""
    # At this point ``my_stage`` is already in the registry, but no built-in
    # module has been imported (mirrors a fresh process + library use).
    assert "my_stage" in registry_module._STAGE_REGISTRY
    assert "rate_limit" not in registry_module._STAGE_REGISTRY

    runner = build_pipeline_from_config([{"type": "rate_limit"}])

    names = [type(s).__name__ for s in runner.stages]
    assert names == ["RateLimitStage"], names


async def test_all_builtins_available_alongside_custom_stage():
    """All seven built-ins register even when a custom stage registered first."""
    runner = build_pipeline_from_config(
        [
            {"type": "rate_limit"},
            {"type": "cost_guard"},
            {"type": "input_validation"},
            {"type": "llm_provider"},
            {"type": "mcp_registry"},
            {"type": "credential_resolver"},
            {"type": "skill_registry"},
            {"type": "my_stage"},
        ]
    )
    names = [type(s).__name__ for s in runner.stages]
    assert len(names) == 8, names
    assert "RateLimitStage" in names
    assert "MyStage" in names


async def test_builtins_register_once():
    """Built-in import is idempotent and leaves every built-in available."""
    build_pipeline_from_config([])
    first = set(registry_module._STAGE_REGISTRY)
    build_pipeline_from_config([])
    assert set(registry_module._STAGE_REGISTRY) == first

    for builtin in ("rate_limit", "cost_guard", "input_validation", "llm_provider",
                    "mcp_registry", "credential_resolver", "skill_registry"):
        assert builtin in registry_module._STAGE_REGISTRY, builtin
