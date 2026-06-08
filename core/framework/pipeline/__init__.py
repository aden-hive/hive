"""Pipeline middleware for the agent runtime.

Stages run in order when :meth:`AgentRuntime.trigger` receives a request.
Each stage can pass the context through, transform the input data, or reject
the request entirely.  This is the runtime-level analogue of AstrBot's
pipeline architecture and lets operators compose rate limiting, validation,
cost guards, and custom pre/post-processing without patching core code.
"""

from framework.pipeline.registry import (
    build_pipeline_from_config,
    build_stage,
    register,
)
from framework.pipeline.runner import PipelineRunner
from framework.pipeline.stage import (
    PipelineContext,
    PipelineRejectedError,
    PipelineResult,
    PipelineStage,
)

__all__ = [
    "PipelineContext",
    "PipelineRejectedError",
    "PipelineResult",
    "PipelineRunner",
    "PipelineStage",
    "build_pipeline_from_config",
    "build_stage",
    "register",
]
