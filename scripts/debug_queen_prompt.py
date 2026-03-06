#!/usr/bin/env python
"""Debug tool to print the queen's running phase prompt."""

from framework.agents.hive_coder.nodes import (
    _appendices,
    _queen_behavior_always,
    _queen_behavior_running,
    _queen_identity_running,
    _queen_style,
    _queen_tools_running,
)


def print_running_prompt(worker_identity: str | None = None) -> None:
    """Print the composed running phase prompt.

    Args:
        worker_identity: Optional worker identity string. If None, shows
            the "no worker loaded" placeholder.
    """
    if worker_identity is None:
        worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Handle all tasks directly using your coding tools."
        )

    prompt = (
        _queen_identity_running
        + _queen_tools_running
        + _queen_behavior_always
        + _queen_behavior_running
        + _queen_style
        + worker_identity
    )

    print("=" * 80)
    print("QUEEN RUNNING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


def print_building_prompt(worker_identity: str | None = None) -> None:
    """Print the composed building phase prompt."""
    from framework.agents.hive_coder.nodes import (
        _agent_builder_knowledge,
        _queen_behavior_building,
        _queen_identity_building,
        _queen_phase_7,
        _queen_tools_building,
    )

    if worker_identity is None:
        worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Handle all tasks directly using your coding tools."
        )

    prompt = (
        _queen_identity_building
        + _agent_builder_knowledge
        + _queen_tools_building
        + _queen_behavior_always
        + _queen_behavior_building
        + _queen_phase_7
        + _queen_style
        + _appendices
        + worker_identity
    )

    print("=" * 80)
    print("QUEEN BUILDING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


def print_staging_prompt(worker_identity: str | None = None) -> None:
    """Print the composed staging phase prompt."""
    from framework.agents.hive_coder.nodes import (
        _queen_behavior_staging,
        _queen_identity_staging,
        _queen_tools_staging,
    )

    if worker_identity is None:
        worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Handle all tasks directly using your coding tools."
        )

    prompt = (
        _queen_identity_staging
        + _queen_tools_staging
        + _queen_behavior_always
        + _queen_behavior_staging
        + _queen_style
        + worker_identity
    )

    print("=" * 80)
    print("QUEEN STAGING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


if __name__ == "__main__":
    import sys

    phase = sys.argv[1] if len(sys.argv) > 1 else "running"

    if phase == "all":
        print_building_prompt()
        print("\n\n")
        print_staging_prompt()
        print("\n\n")
        print_running_prompt()
    elif phase == "building":
        print_building_prompt()
    elif phase == "staging":
        print_staging_prompt()
    elif phase == "running":
        print_running_prompt()
    else:
        print(f"Unknown phase: {phase}")
        print("Usage: uv run scripts/debug_queen_prompt.py [building|staging|running|all]")
        sys.exit(1)
