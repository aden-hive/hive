"""Legacy compatibility wrapper around :mod:`framework.graph.prompting`.

New runtime code should import from ``framework.graph.prompting`` directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from framework.orchestrator.prompting import (
    EXECUTION_SCOPE_PREAMBLE,
    TransitionSpec,
    build_accounts_prompt,
    build_narrative,
    build_system_prompt,
    stamp_prompt_datetime,
)

if TYPE_CHECKING:
    from framework.orchestrator.node import DataBuffer, NodeSpec


_with_datetime = stamp_prompt_datetime


def compose_system_prompt(
    identity_prompt: str | None,
    focus_prompt: str | None,
    narrative: str | None = None,
    accounts_prompt: str | None = None,
    skills_catalog_prompt: str | None = None,
    protocols_prompt: str | None = None,
    execution_preamble: str | None = None,
    node_type_preamble: str | None = None,
) -> str:
    """Compatibility wrapper for the legacy function signature."""
    from framework.orchestrator.prompting import NodePromptSpec

    spec = NodePromptSpec(
        identity_prompt=identity_prompt or "",
        focus_prompt=focus_prompt or "",
        narrative=narrative or "",
        accounts_prompt=accounts_prompt or "",
        skills_catalog_prompt=skills_catalog_prompt or "",
        protocols_prompt=protocols_prompt or "",
        # Legacy callers explicitly passed these preambles. Preserve them by
        # folding them into the focus block when present.
        node_type="event_loop",
    )
    if execution_preamble or node_type_preamble:
        focus_parts = []
        if execution_preamble:
            focus_parts.append(execution_preamble)
        if node_type_preamble:
            focus_parts.append(node_type_preamble)
        if spec.focus_prompt:
            focus_parts.append(spec.focus_prompt)
        spec = NodePromptSpec(
            identity_prompt=spec.identity_prompt,
            focus_prompt="\n\n".join(focus_parts),
            narrative=spec.narrative,
            accounts_prompt=spec.accounts_prompt,
            skills_catalog_prompt=spec.skills_catalog_prompt,
            protocols_prompt=spec.protocols_prompt,
            node_type=spec.node_type,
            output_keys=spec.output_keys,
        )
    return build_system_prompt(spec)


def build_transition_marker(
    previous_node: NodeSpec,
    next_node: NodeSpec,
    buffer: DataBuffer,
    cumulative_tool_names: list[str],
    data_dir: Path | str | None = None,
) -> str:
    """Legacy transition builder with best-effort spillover compatibility."""
    buffer_items: dict[str, str] = {}
    data_files: list[str] = []

    all_buffer = buffer.read_all()
    for key, value in all_buffer.items():
        if value is None:
            continue
        val_str = str(value)
        if len(val_str) > 300 and data_dir:
            data_path = Path(data_dir)
            data_path.mkdir(parents=True, exist_ok=True)
            ext = ".json" if isinstance(value, (dict, list)) else ".txt"
            filename = f"output_{key}{ext}"
            file_path = data_path / filename
            try:
                write_content = (
                    json.dumps(value, indent=2, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                file_path.write_text(write_content, encoding="utf-8")
                file_size = file_path.stat().st_size
                buffer_items[key] = (
                    f"[Saved to '{filename}' ({file_size:,} bytes). "
                    f"Use read_file(path='{filename}') to access.]"
                )
            except Exception:
                buffer_items[key] = val_str[:300] + "..."
        elif len(val_str) > 300:
            buffer_items[key] = val_str[:300] + "..."
        else:
            buffer_items[key] = val_str

    if data_dir:
        data_path = Path(data_dir)
        if data_path.exists():
            data_files = [
                f"{entry.name} ({entry.stat().st_size:,} bytes)"
                for entry in sorted(data_path.iterdir())
                if entry.is_file()
            ]

    return build_transition_message(
        TransitionSpec(
            previous_name=previous_node.name,
            previous_description=previous_node.description,
            next_name=next_node.name,
            next_description=next_node.description,
            next_output_keys=tuple(next_node.output_keys or ()),
            buffer_items=buffer_items,
            cumulative_tool_names=tuple(sorted(cumulative_tool_names)),
            data_files=tuple(data_files),
        )
    )


from framework.orchestrator.prompting import build_transition_message  # noqa: E402

__all__ = [
    "EXECUTION_SCOPE_PREAMBLE",
    "_with_datetime",
    "build_accounts_prompt",
    "build_narrative",
    "build_transition_marker",
    "build_transition_message",
    "compose_system_prompt",
]
