#!/usr/bin/env python3
"""Test tool to visualize the Queen's building phase system prompt."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "core"))

from framework.agents.hive_coder.nodes import (
    _queen_identity,
    _agent_builder_knowledge,
    _gcu_building_section,
    _queen_tools_docs,
    _queen_behavior,
    _queen_phase_7,
    _queen_style,
    _appendices,
    queen_node,
    _is_gcu_enabled,
)


def print_section_header(title: str, char: str = "=") -> None:
    """Print a section header."""
    print(f"\n{char * 80}")
    print(f" {title}")
    print(f"{char * 80}\n")


def print_subsection_header(title: str) -> None:
    """Print a subsection header."""
    print(f"\n{'-' * 80}")
    print(f" {title}")
    print(f"{'-' * 80}\n")


def count_lines(text: str) -> int:
    """Count non-empty lines in text."""
    return len([line for line in text.split("\n") if line.strip()])


def analyze_prompt():
    """Analyze and display the Queen's building phase system prompt."""
    print_section_header("QUEEN BUILDING PHASE PROMPT ANALYZER")

    # Show GCU status
    gcu_enabled = _is_gcu_enabled()
    print(f"GCU Enabled: {gcu_enabled}")
    print(f"GCU Section Length: {len(_gcu_building_section)} chars, {count_lines(_gcu_building_section)} lines")

    # Build the full prompt
    full_prompt = (
        _queen_identity
        + _agent_builder_knowledge
        + _gcu_building_section
        + _queen_tools_docs
        + _queen_behavior
        + _queen_phase_7
        + _queen_style
        + _appendices
    )

    print(f"\nFull Prompt Length: {len(full_prompt)} chars, {count_lines(full_prompt)} lines")

    # Show section breakdown
    print_subsection_header("SECTION BREAKDOWN")
    sections = [
        ("_queen_identity", _queen_identity),
        ("_agent_builder_knowledge", _agent_builder_knowledge),
        ("_gcu_building_section", _gcu_building_section),
        ("_queen_tools_docs", _queen_tools_docs),
        ("_queen_behavior", _queen_behavior),
        ("_queen_phase_7", _queen_phase_7),
        ("_queen_style", _queen_style),
        ("_appendices", _appendices),
    ]

    print(f"{'Section':<30} {'Chars':>10} {'Lines':>10} {'%':>8}")
    print("-" * 60)

    total_chars = sum(len(s[1]) for s in sections)
    for name, content in sections:
        chars = len(content)
        lines = count_lines(content)
        pct = (chars / total_chars * 100) if total_chars > 0 else 0
        print(f"{name:<30} {chars:>10} {lines:>10} {pct:>7.1f}%")

    print("-" * 60)
    print(f"{'TOTAL':<30} {total_chars:>10} {count_lines(full_prompt):>10} {'100.0':>7}%")

    # Show prompt structure
    print_subsection_header("PROMPT STRUCTURE (First 200 chars of each section)")

    for name, content in sections:
        if content.strip():
            print(f"\n### {name} ###")
            preview = content[:200].strip()
            if len(content) > 200:
                preview += "..."
            print(preview)

    return full_prompt


def print_full_prompt():
    """Print the full Queen system prompt."""
    print_section_header("FULL QUEEN SYSTEM PROMPT")

    full_prompt = queen_node.system_prompt
    print(full_prompt)

    print_section_header("END OF PROMPT")
    print(f"Total length: {len(full_prompt)} characters")


def print_gcu_section():
    """Print just the GCU section to verify it's first-class."""
    print_section_header("GCU BUILDING SECTION (First-Class)")

    if _gcu_building_section:
        print(_gcu_building_section)
    else:
        print("(GCU is disabled or section is empty)")

    print_section_header("END OF GCU SECTION")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Queen's building phase prompt")
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Print the full system prompt"
    )
    parser.add_argument(
        "--gcu", "-g",
        action="store_true",
        help="Print just the GCU section"
    )
    parser.add_argument(
        "--structure", "-s",
        action="store_true",
        default=True,
        help="Show prompt structure analysis (default)"
    )

    args = parser.parse_args()

    if args.full:
        print_full_prompt()
    elif args.gcu:
        print_gcu_section()
    else:
        analyze_prompt()
