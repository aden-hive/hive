"""Agent picker ModalScreen for selecting agents within the TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, TabbedContent, TabPane
from textual.widgets._option_list import Option


class GetStartedAction(Enum):
    """Actions available in the Get Started tab."""

    RUN_EXAMPLES = "run_examples"
    RUN_EXISTING = "run_existing"
    BUILD_EDIT = "build_edit"


@dataclass
class AgentEntry:
    """Lightweight agent metadata for the picker."""

    path: Path
    name: str
    description: str
    category: str
    session_count: int = 0
    node_count: int = 0
    tool_count: int = 0
    tags: list[str] = field(default_factory=list)


def _count_sessions(agent_name: str) -> int:
    """Count session directories under ~/.hive/agents/{agent_name}/sessions/."""
    sessions_dir = Path.home() / ".hive" / "agents" / agent_name / "sessions"
    if not sessions_dir.exists():
        return 0
    return sum(1 for d in sessions_dir.iterdir() if d.is_dir() and d.name.startswith("session_"))


def _extract_agent_stats(agent_json_path: Path) -> tuple[int, int, list[str]]:
    """Extract node count, tool count, and tags from agent.json."""
    try:
        data = json.loads(agent_json_path.read_text())
        nodes = data.get("nodes", [])
        node_count = len(nodes)
        tools: set[str] = set()
        for node in nodes:
            tools.update(node.get("tools", []))
        tags = data.get("agent", {}).get("tags", [])
        return node_count, len(tools), tags
    except Exception:
        return 0, 0, []


def discover_agents() -> dict[str, list[AgentEntry]]:
    """Discover agents from all known sources grouped by category."""
    from framework.runner.cli import (
        _extract_python_agent_metadata,
        _get_framework_agents_dir,
        _is_valid_agent_dir,
    )

    groups: dict[str, list[AgentEntry]] = {}
    sources = [
        ("Your Agents", Path("exports")),
        ("Framework", _get_framework_agents_dir()),
        ("Examples", Path("examples/templates")),
    ]

    for category, base_dir in sources:
        if not base_dir.exists():
            continue
        entries: list[AgentEntry] = []
        for path in sorted(base_dir.iterdir(), key=lambda p: p.name):
            if not _is_valid_agent_dir(path):
                continue

            agent_json = path / "agent.json"
            node_count, tool_count, tags = 0, 0, []
            if agent_json.exists():
                try:
                    data = json.loads(agent_json.read_text())
                    meta = data.get("agent", {})
                    name = meta.get("name", path.name)
                    desc = meta.get("description", "")
                except Exception:
                    name = path.name
                    desc = "(error reading agent.json)"
                node_count, tool_count, tags = _extract_agent_stats(agent_json)
            else:
                name, desc = _extract_python_agent_metadata(path)

            entries.append(
                AgentEntry(
                    path=path,
                    name=name,
                    description=desc,
                    category=category,
                    session_count=_count_sessions(path.name),
                    node_count=node_count,
                    tool_count=tool_count,
                    tags=tags,
                )
            )
        if entries:
            groups[category] = entries

    return groups


def _render_agent_option(agent: AgentEntry) -> Group:
    """Build a Rich renderable for a single agent option."""
    # Line 1: name + session badge
    line1 = Text()
    line1.append(agent.name, style="bold")
    if agent.session_count:
        line1.append(f"  {agent.session_count} sessions", style="dim cyan")

    # Line 2: description (word-wrapped by the widget)
    desc = agent.description if agent.description else "No description"
    line2 = Text(desc, style="dim")

    # Line 3: stats chips
    chips = Text()
    if agent.node_count:
        chips.append(f" {agent.node_count} nodes ", style="on dark_green white")
        chips.append(" ")
    if agent.tool_count:
        chips.append(f" {agent.tool_count} tools ", style="on dark_blue white")
        chips.append(" ")
    for tag in agent.tags[:3]:
        chips.append(f" {tag} ", style="on grey37 white")
        chips.append(" ")

    parts = [line1, line2]
    if chips.plain.strip():
        parts.append(chips)
    return Group(*parts)


def _render_get_started_option(title: str, description: str, icon: str = "→") -> Group:
    """Build a Rich renderable for a Get Started option."""
    line1 = Text()
    line1.append(f"{icon} ", style="bold cyan")
    line1.append(title, style="bold")
    line2 = Text(description, style="dim")
    return Group(line1, line2)


class AgentPickerScreen(ModalScreen[str | None]):
    """Modal screen showing available agents organized by tabbed categories.

    Returns the selected agent path as a string, or None if dismissed.
    For Get Started actions, returns a special prefix like "action:run_examples".
    """

    BINDINGS = [
        Binding("escape", "dismiss_picker", "Cancel"),
    ]

    DEFAULT_CSS = """
    AgentPickerScreen {
        align: center middle;
    }
    #picker-container {
        width: 90%;
        max-width: 120;
        height: 85%;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }
    #picker-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        color: $text;
    }
    #picker-subtitle {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    #picker-footer {
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    TabPane {
        padding: 0;
    }
    OptionList {
        height: 1fr;
    }
    OptionList > .option-list--option {
        padding: 1 2;
    }
    """

    def __init__(
        self,
        agent_groups: dict[str, list[AgentEntry]],
        show_get_started: bool = False,
    ) -> None:
        super().__init__()
        self._groups = agent_groups
        self._show_get_started = show_get_started
        # Map (tab_id, option_index) -> AgentEntry
        self._option_map: dict[str, dict[int, AgentEntry]] = {}

    def compose(self) -> ComposeResult:
        total = sum(len(v) for v in self._groups.values())
        with Vertical(id="picker-container"):
            yield Label("Hive Agent Launcher", id="picker-title")
            yield Label(
                f"[dim]{total} agents available[/dim]",
                id="picker-subtitle",
            )
            with TabbedContent():
                # Get Started tab (only on initial launch)
                if self._show_get_started:
                    with TabPane("Get Started", id="get-started"):
                        option_list = OptionList(id="list-get-started")
                        option_list.add_option(
                            Option(
                                _render_get_started_option(
                                    "Test and run example agents",
                                    "Try pre-built example agents to learn how Hive works",
                                    "📚",
                                ),
                                id="action:run_examples",
                            )
                        )
                        option_list.add_option(
                            Option(
                                _render_get_started_option(
                                    "Test and run existing agent",
                                    "Load and run an agent you've already built (from exports/)",
                                    "🚀",
                                ),
                                id="action:run_existing",
                            )
                        )
                        option_list.add_option(
                            Option(
                                _render_get_started_option(
                                    "Build or edit agent",
                                    "Create a new agent or modify an existing one",
                                    "🛠️ ",
                                ),
                                id="action:build_edit",
                            )
                        )
                        yield option_list

                # Agent category tabs
                for category, agents in self._groups.items():
                    tab_id = category.lower().replace(" ", "-")
                    with TabPane(f"{category} ({len(agents)})", id=tab_id):
                        option_list = OptionList(id=f"list-{tab_id}")
                        self._option_map[f"list-{tab_id}"] = {}
                        for i, agent in enumerate(agents):
                            option_list.add_option(
                                Option(
                                    _render_agent_option(agent),
                                    id=str(agent.path),
                                )
                            )
                            self._option_map[f"list-{tab_id}"][i] = agent
                        yield option_list
            yield Label(
                "[dim]Enter[/dim] Select  [dim]Tab[/dim] Switch category  [dim]Esc[/dim] Cancel",
                id="picker-footer",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        list_id = event.option_list.id or ""

        # Handle Get Started tab options
        if list_id == "list-get-started":
            option = event.option
            if option and option.id:
                self.dismiss(option.id)  # Returns "action:run_examples", etc.
            return

        # Handle agent selection from other tabs
        idx = event.option_index
        agent_map = self._option_map.get(list_id, {})
        agent = agent_map.get(idx)
        if agent:
            self.dismiss(str(agent.path))

    def action_dismiss_picker(self) -> None:
        self.dismiss(None)
