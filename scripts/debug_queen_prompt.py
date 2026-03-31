#!/usr/bin/env python
"""Debug tool to print the queen's phase-specific prompts."""

from framework.agents.queen.nodes import (
    _appendices,
    _queen_behavior_always,
    _queen_behavior_running,
    _queen_identity_running,
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
        _queen_identity_planning,
        _queen_tools_planning,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_identity_planning
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
        _queen_identity_building,
        _queen_phase_7,
        _queen_tools_building,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_identity_building
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
        _queen_identity_staging,
        _queen_tools_staging,
    )

    wi = worker_identity or _DEFAULT_WORKER_IDENTITY

    prompt = (
        _queen_identity_staging
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
        _queen_identity_running
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
        description="Print queen prompts for a specific phase."
    )
    parser.add_argument(
        "phase",
        nargs="?",
        default="planning",
        choices=["planning", "building", "staging", "running", "all"],
        help="Which phase prompt to print (default: planning).",
    )
    parser.add_argument(
        "-w",
        "--worker",
        dest="worker_identity",
        default=None,
        help="Optional worker identity string to append to the prompt.",
    )
    args = parser.parse_args()

    if args.phase == "all":
        print_planning_prompt(args.worker_identity)
        print("\n\n")
        print_building_prompt(args.worker_identity)
        print("\n\n")
        print_staging_prompt(args.worker_identity)
        print("\n\n")
        print_running_prompt(args.worker_identity)
    elif args.phase == "planning":
        print_planning_prompt(args.worker_identity)
    elif args.phase == "building":
        print_building_prompt(args.worker_identity)
    elif args.phase == "staging":
        print_staging_prompt(args.worker_identity)
    elif args.phase == "running":
        print_running_prompt(args.worker_identity)
