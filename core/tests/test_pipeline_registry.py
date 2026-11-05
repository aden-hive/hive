"""Regression test for issue #7515.

build_pipeline_from_config() must load built-in stages even when a
custom stage registered first made the registry look already populated.

Runs in a subprocess so the built-in ``rate_limit`` module is not already
imported (and thus not already registered) by anything else in the test
session -- that's exactly the ordering the original bug depended on.
"""

import subprocess
import sys
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent.parent

_REPRO = """
import sys
from framework.pipeline import build_pipeline_from_config, register
from framework.pipeline.stage import PipelineStage

@register("my_custom_stage_7515")
class MyStage(PipelineStage):
    async def process(self, ctx):
        raise NotImplementedError

runner = build_pipeline_from_config([{"type": "rate_limit"}])
assert any(type(stage).__name__ == "RateLimitStage" for stage in runner.stages)
"""


def test_builtin_stage_available_after_custom_stage_registers_first():
    result = subprocess.run(
        [sys.executable, "-c", _REPRO],
        capture_output=True,
        text=True,
        cwd=_CORE_DIR,
    )
    assert result.returncode == 0, result.stderr
