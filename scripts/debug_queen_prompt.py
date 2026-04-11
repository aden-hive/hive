#!/usr/bin/env python
"""Debug tool to print the queen's phase-specific prompts."""

from framework.agents.queen.nodes import (
    _appendices,
    _queen_behavior_always,
    _queen_behavior_running,
    _queen_character_core,
    _queen_role_running,
    _queen_style,
    _queen_tools_running,
)

_DEFAULT_WORKER_IDENTITY = (
    "\n\n# Worker Profile\n"
    "No worker agent loaded. You are operating independently.\n"
    "Design or build the agent to solve the user's problem "
    "according to your current phase."
)


def print_planning_prompt(worker_identity: str | None = None) -> None:
    """Print the composed planning phase prompt."""
    from framework.agents.queen.nodes import (
        _planning_knowledge,
        _queen_behavior_planning,
        _queen_role_planning,
        _queen_tools_planning,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_character_core
        + _queen_role_planning
        + _queen_style
        + _queen_tools_planning
        + _queen_behavior_always
        + _queen_behavior_planning
        + _planning_knowledge
        + wi
    )

    print("=" * 80)
    print("QUEEN PLANNING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


def print_building_prompt(worker_identity: str | None = None) -> None:
    """Print the composed building phase prompt."""
    from framework.agents.queen.nodes import (
        _building_knowledge,
        _gcu_building_section,
        _queen_behavior_building,
        _queen_phase_7,
        _queen_role_building,
        _queen_tools_building,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_character_core
        + _queen_role_building
        + _queen_style
        + _queen_tools_building
        + _queen_behavior_always
        + _queen_behavior_building
        + _building_knowledge
        + _gcu_building_section
        + _queen_phase_7
        + _appendices
        + wi
    )

    print("=" * 80)
    print("QUEEN BUILDING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


def print_staging_prompt(worker_identity: str | None = None) -> None:
    """Print the composed staging phase prompt."""
    from framework.agents.queen.nodes import (
        _queen_behavior_staging,
        _queen_role_staging,
        _queen_tools_staging,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_character_core
        + _queen_role_staging
        + _queen_style
        + _queen_tools_staging
        + _queen_behavior_always
        + _queen_behavior_staging
        + wi
    )

    print("=" * 80)
    print("QUEEN STAGING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


def print_running_prompt(worker_identity: str | None = None) -> None:
    """Print the composed running phase prompt.

    Args:
        worker_identity: Optional worker identity string. If None, shows
            the "no worker loaded" placeholder.
    """
    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_character_core
        + _queen_role_running
        + _queen_style
        + _queen_tools_running
        + _queen_behavior_always
        + _queen_behavior_running
        + wi
    )

    print("=" * 80)
    print("QUEEN RUNNING PHASE PROMPT")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"\nTotal length: {len(prompt):,} characters")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Print the queen's phase-specific prompts."
    )
    parser.add_argument(
        "phase",
        nargs="?",
        default="planning",
        choices=["planning", "building", "staging", "running", "all"],
        help="Phase to print (default: planning)",
    )
    parser.add_argument(
        "-w",
        "--worker",
        metavar="WORKER_IDENTITY",
        default=None,
        help="Worker identity string to inject into the prompt",
    )
    args = parser.parse_args()

    phase = args.phase
    worker = args.worker

    if phase == "all":
        print_planning_prompt(worker)
        print("\n\n")
        print_building_prompt(worker)
        print("\n\n")
        print_staging_prompt(worker)
        print("\n\n")
        print_running_prompt(worker)
    elif phase == "planning":
        print_planning_prompt(worker)
    elif phase == "building":
        print_building_prompt(worker)
    elif phase == "staging":
        print_staging_prompt(worker)
    elif phase == "running":
        print_running_prompt(worker)
