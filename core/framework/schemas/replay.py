"""Schemas for deterministic replay of agent sessions (issue #4669)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReplayConfig(BaseModel):
    """Configuration for replaying a previous session deterministically.

    Loads cached LLM responses and tool results from the source session's
    L3 tool_logs.jsonl and replays them instead of calling live systems.

    Example::

        config = ReplayConfig(
            source_session_id="session_20260304_143022_abc12345",
            freeze_llm=True,
            freeze_tools=True,
        )
        result = await runner.run_replay(config)

    Counterfactual mode (live LLM on frozen tool data)::

        config = ReplayConfig(
            source_session_id="session_20260304_143022_abc12345",
            freeze_llm=False,
            freeze_tools=True,
            input_overrides={"context": "updated context"},
        )
    """

    source_session_id: str
    """Session ID whose L3 tool_logs.jsonl provides the response cache."""

    from_node: str | None = None
    """Start replay from this node ID. None = run from the agent's entry_point.
    When set, restores SharedMemory from the nearest checkpoint before this node."""

    freeze_llm: bool = True
    """Return cached llm_text instead of calling the live LLM.
    On cache miss the live LLM is called and the miss is counted in ReplayResult."""

    freeze_tools: bool = True
    """Return cached tool results instead of executing tools live.
    On cache miss the live tool is executed and the miss is counted."""

    input_overrides: dict[str, Any] = Field(default_factory=dict)
    """Key-value pairs merged (not replaced) over source session's input_data.
    Allows changing one field without re-specifying all inputs."""


class NodeReplayDiff(BaseModel):
    """Comparison between original and replay execution for a single node."""

    node_id: str

    diverged: bool
    """True if exit_status, success flag, or error presence differ from original."""

    original_exit_status: str
    """exit_status from the source session's L2 NodeDetail (e.g. 'success', 'failure')."""

    replay_exit_status: str
    """exit_status from the replay session's L2 NodeDetail."""

    original_output: dict[str, Any] = Field(default_factory=dict)
    """SharedMemory output keys written by this node in the original run."""

    replay_output: dict[str, Any] = Field(default_factory=dict)
    """SharedMemory output keys written by this node in the replay run."""

    cache_misses: int = 0
    """Number of LLM or tool calls for this node that fell through to live systems."""

    divergence_reason: str | None = None
    """Human-readable description of the first field that differs. None if not diverged."""


class ReplayResult(BaseModel):
    """Full comparison report from a replay run against its source session."""

    source_session_id: str
    """Session that was replayed."""

    replay_session_id: str
    """New session ID created for the replay run."""

    config: ReplayConfig
    """Configuration used for this replay."""

    overall_success: bool
    """Whether the replay run completed successfully."""

    original_success: bool
    """Whether the source session completed successfully."""

    node_diffs: list[NodeReplayDiff] = Field(default_factory=list)
    """Per-node comparison, in original execution order."""

    diverged_nodes: list[str] = Field(default_factory=list)
    """node_id values where diverged=True, for quick scanning."""

    improvement_hypothesis: str = ""
    """Rule-based assessment of what changed between original and replay.
    Generated deterministically — not from an LLM call."""

    total_cache_misses: int = 0
    """Total LLM + tool cache misses across the entire replay run."""

    started_at: str = ""
    """ISO 8601 timestamp when the replay run started."""

    duration_ms: int = 0
    """Wall-clock duration of the replay run in milliseconds."""
