"""Regression test for issue #7515.

build_pipeline_from_config() must load built-in stages even when a
custom stage registered first made the registry look already populated.
"""

from framework.pipeline import build_pipeline_from_config, register
from framework.pipeline.stage import PipelineStage
from framework.pipeline.stages.rate_limit import RateLimitStage


def test_builtin_stage_available_after_custom_stage_registers_first():
    @register("my_custom_stage_7515")
    class MyStage(PipelineStage):
        async def process(self, ctx):
            raise NotImplementedError

    runner = build_pipeline_from_config([{"type": "rate_limit"}])

    assert any(isinstance(stage, RateLimitStage) for stage in runner.stages)
