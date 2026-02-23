import logging
import platform
import subprocess
import threading
import time

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Label

from framework.runtime.event_bus import AgentEvent, EventType
from framework.tui.widgets.selectable_rich_log import SelectableRichLog

# AgentRuntime imported lazily where needed to support runtime=None startup.
# ChatRepl and GraphOverview are imported lazily in _mount_agent_widgets.


class StatusBar(Container):
    """Live status bar showing agent execution state."""

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    StatusBar > Label {
        width: 100%;
    }
    """

    def __init__(self, graph_id: str = ""):
        super().__init__()
        self._graph_id = graph_id
        self._state = "idle"
        self._active_node: str | None = None
        self._node_detail: str = ""
        self._start_time: float | None = None
        self._final_elapsed: float | None = None

    def compose(self) -> ComposeResult:
        yield Label(id="status-content")

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _format_elapsed(self, seconds: float) -> str:
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        mins, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    def _refresh(self) -> None:
        parts: list[str] = []

        if self._graph_id:
            parts.append(f"[bold]{self._graph_id}[/bold]")

        if self._state == "idle":
            parts.append("[dim]○ idle[/dim]")
        elif self._state == "running":
            parts.append("[bold green]● running[/bold green]")
        elif self._state == "completed":
            parts.append("[green]✓ done[/green]")
        elif self._state == "failed":
            parts.append("[bold red]✗ failed[/bold red]")

        if self._active_node:
            node_str = f"[cyan]{self._active_node}[/cyan]"
            if self._node_detail:
                node_str += f" [dim]({self._node_detail})[/dim]"
            parts.append(node_str)

        if self._state == "running" and self._start_time:
            parts.append(f"[dim]{self._format_elapsed(time.time() - self._start_time)}[/dim]")
        elif self._final_elapsed is not None:
            parts.append(f"[dim]{self._format_elapsed(self._final_elapsed)}[/dim]")

        try:
            label = self.query_one("#status-content", Label)
            label.update(" │ ".join(parts))
        except Exception:
            pass

    def set_graph_id(self, graph_id: str) -> None:
        self._graph_id = graph_id
        self._refresh()

    def set_running(self, entry_node: str = "") -> None:
        self._state = "running"
        self._active_node = entry_node or None
        self._node_detail = ""
        self._start_time = time.time()
        self._final_elapsed = None
        self._refresh()

    def set_completed(self) -> None:
        self._state = "completed"
        if self._start_time:
            self._final_elapsed = time.time() - self._start_time
        self._active_node = None
        self._node_detail = ""
        self._start_time = None
        self._refresh()

    def set_failed(self, error: str = "") -> None:
        self._state = "failed"
        if self._start_time:
            self._final_elapsed = time.time() - self._start_time
        self._node_detail = error[:40] if error else ""
        self._start_time = None
        self._refresh()

    def set_active_node(self, node_id: str, detail: str = "") -> None:
        self._active_node = node_id
        self._node_detail = detail
        self._refresh()

    def set_node_detail(self, detail: str) -> None:
        self._node_detail = detail
        self._refresh()


class AdenTUI(App):
    TITLE = "Aden TUI Dashboard"
    COMMAND_PALETTE_BINDING = "ctrl+o"
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    GraphOverview {
        width: 40%;
        height: 100%;
        background: $panel;
        padding: 0;
    }

    ChatRepl {
        width: 60%;
        height: 100%;
        background: $panel;
        border-left: tall $primary;
        padding: 0;
    }

    #agent-workspace {
        height: 1fr;
    }

    #chat-history {
        height: 1fr;
        width: 100%;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    RichLog {
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    ChatTextArea {
        background: $surface;
        border: tall $primary;
        margin-top: 1;
    }

    ChatTextArea:focus {
        border: tall $accent;
    }

    StatusBar {
        background: $panel;
        color: $text;
        height: 1;
        padding: 0 1;
    }

    Footer {
        background: $panel;
        color: $text-muted;
    }

    #empty-workspace {
        align: center middle;
        height: 1fr;
    }

    #empty-workspace Label {
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "ctrl_c", "Interrupt", show=False, priority=True),
        Binding("super+c", "ctrl_c", "Copy", show=False, priority=True),
        Binding("ctrl+s", "screenshot", "Screenshot (SVG)", show=True, priority=True),
        Binding("ctrl+l", "toggle_logs", "Toggle Logs", show=True, priority=True),
        Binding("ctrl+z", "pause_execution", "Pause", show=True, priority=True),
        Binding("ctrl+r", "show_sessions", "Sessions", show=True, priority=True),
        Binding("ctrl+a", "show_agent_picker", "Agents", show=True, priority=True),
        Binding("ctrl+e", "escalate_to_coder", "Coder", show=True, priority=True),
        Binding("ctrl+e", "return_from_coder", "← Back", show=True, priority=True),
        Binding("ctrl+q", "connect_to_queen", "Queen", show=True, priority=True),
        Binding("tab", "focus_next", "Next Panel", show=True),
        Binding("shift+tab", "focus_previous", "Previous Panel", show=False),
    ]

    def __init__(
        self,
        runtime=None,
        resume_session: str | None = None,
        resume_checkpoint: str | None = None,
        model: str | None = None,
    ):
        super().__init__()

        self.runtime = runtime
        self._model = model
        self._resume_session = resume_session
        self._resume_checkpoint = resume_checkpoint
        self._runner = None  # AgentRunner — needed for cleanup on swap

        # Escalation stack: stores worker state when coder is in foreground
        self._escalation_stack: list[dict] = []

        # Health judge + queen monitoring graphs (loaded alongside worker agents)
        self._queen_graph_id: str | None = None
        self._judge_graph_id: str | None = None
        self._queen_agent = None  # HiveCoderAgent instance — kept alive to hold MCP process

        # Widgets are created lazily when runtime is available
        self.graph_view = None
        self.chat_repl = None
        self.status_bar = StatusBar(graph_id=runtime.graph.id if runtime else "")
        self.is_ready = False

    def open_url(self, url: str, *, new_tab: bool = True) -> None:
        """Override to use native `open` for file:// URLs on macOS."""
        if url.startswith("file://") and platform.system() == "Darwin":
            path = url.removeprefix("file://")
            subprocess.Popen(["open", path])
        else:
            super().open_url(url, new_tab=new_tab)

    def action_ctrl_c(self) -> None:
        # Check if any SelectableRichLog has an active selection to copy
        for widget in self.query(SelectableRichLog):
            if widget.selection is not None:
                text = widget.copy_selection()
                if text:
                    widget.clear_selection()
                    self.notify("Copied to clipboard", severity="information", timeout=2)
                    return

        self.notify("Press [b]q[/b] to quit", severity="warning", timeout=3)

    def compose(self) -> ComposeResult:
        yield self.status_bar
        yield Horizontal(id="agent-workspace")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when app starts."""
        self.title = "Aden TUI Dashboard"
        self._setup_logging_queue()
        self.is_ready = True

        if self.runtime is not None:
            # Direct launch with agent already loaded
            self._mount_agent_widgets()
            self.call_later(self._init_runtime_connection)

            def write_initial_logs():
                logging.info("TUI Dashboard initialized successfully")
                logging.info("Waiting for agent execution to start...")

            self.set_timer(0.2, write_initial_logs)
        else:
            # No agent — show picker
            self.call_later(self._show_agent_picker_initial)

    # -- Agent widget lifecycle --

    def _mount_agent_widgets(self) -> None:
        """Mount ChatRepl and GraphOverview into #agent-workspace."""
        from framework.tui.widgets.chat_repl import ChatRepl
        from framework.tui.widgets.graph_view import GraphOverview

        workspace = self.query_one("#agent-workspace", Horizontal)

        # Remove empty-state placeholder if present
        for child in list(workspace.children):
            child.remove()

        self.graph_view = GraphOverview(self.runtime)
        self.chat_repl = ChatRepl(
            self.runtime,
            self._resume_session,
            self._resume_checkpoint,
        )
        workspace.mount(self.graph_view)
        workspace.mount(self.chat_repl)
        self.status_bar.set_graph_id(self.runtime.graph.id)

    def _unmount_agent_widgets(self) -> None:
        """Remove ChatRepl and GraphOverview from #agent-workspace."""
        # Unsubscribe from events
        if hasattr(self, "_subscription_id"):
            try:
                self.runtime.unsubscribe_from_events(self._subscription_id)
            except Exception:
                pass
            del self._subscription_id

        workspace = self.query_one("#agent-workspace", Horizontal)
        for child in list(workspace.children):
            child.remove()

        self.graph_view = None
        self.chat_repl = None

    async def _load_and_switch_agent(self, agent_path: str) -> None:
        """Load an agent and replace the current one in the TUI."""
        from pathlib import Path

        from framework.credentials.models import CredentialError
        from framework.runner import AgentRunner

        # 1. Tear down old agent
        if self.runtime is not None:
            self._unmount_agent_widgets()
            if self._runner is not None:
                try:
                    await self._runner.cleanup_async()
                except Exception:
                    pass
                self._runner = None
            self.runtime = None

        # 2. Show loading state
        agent_name = Path(agent_path).name
        self.status_bar.set_graph_id(f"Loading {agent_name}...")
        self.notify(f"Loading agent: {agent_name}...", timeout=3)

        # 3. Load new agent (run blocking I/O in thread to avoid freezing the TUI)
        import asyncio
        import functools

        loop = asyncio.get_event_loop()
        try:
            load_fn = functools.partial(
                AgentRunner.load,
                agent_path,
                model=self._model,
                interactive=False,
            )
            runner = await loop.run_in_executor(None, load_fn)
        except CredentialError as e:
            self.status_bar.set_graph_id("")
            self._show_credential_setup(
                str(agent_path),
                credential_error=e,
            )
            return
        except Exception as e:
            self.status_bar.set_graph_id("")
            self.notify(f"Failed to load agent: {e}", severity="error", timeout=10)
            return

        # 4. Pre-run account selection (if agent requires it)
        if runner.requires_account_selection and runner._configure_for_account:
            try:
                if runner._list_accounts:
                    accounts = await loop.run_in_executor(None, runner._list_accounts)
                else:
                    accounts = []
            except Exception as e:
                self.notify(f"Failed to list accounts: {e}", severity="error", timeout=10)
                accounts = []
            if accounts:
                self._show_account_selection(runner, accounts)
                return  # Continuation via callback

        # 5. Complete the load
        await self._finish_agent_load(runner)

    async def _finish_agent_load(self, runner) -> None:
        """Complete agent setup and widget mount."""
        import asyncio

        # Reset health monitoring state from any prior agent load
        self._queen_graph_id = None
        self._judge_graph_id = None
        self._queen_agent = None

        loop = asyncio.get_event_loop()
        try:
            if runner._agent_runtime is None:
                await loop.run_in_executor(None, runner._setup)

            self._runner = runner
            self.runtime = runner._agent_runtime
        except Exception as e:
            self.status_bar.set_graph_id("")
            self.notify(f"Failed to load agent: {e}", severity="error", timeout=10)
            return

        # Mount widgets FIRST — creates the ChatRepl and its dedicated agent
        # event loop on a background thread.
        self._mount_agent_widgets()

        # Start the runtime on the agent loop so ALL async tasks (timers,
        # event handlers, execution streams) live on the same loop as worker
        # execution.  Previously runtime.start() ran on Textual's UI loop,
        # causing timer tasks to be starved by UI rendering.
        if self.runtime and not self.runtime.is_running:
            try:
                agent_loop = self.chat_repl._agent_loop
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.start(), agent_loop
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self.status_bar.set_graph_id("")
                self.notify(f"Failed to start runtime: {e}", severity="error", timeout=10)
                return

        await self._init_runtime_connection()

        # Clear resume state for subsequent loads
        self._resume_session = None
        self._resume_checkpoint = None

        agent_name = runner.agent_path.name
        self.notify(f"Agent loaded: {agent_name}", severity="information", timeout=3)

        # Load health judge + queen for worker agents (skip for hive_coder itself)
        if agent_name != "hive_coder":
            await self._load_judge_and_queen(runner._storage_path)

    async def _load_judge_and_queen(self, storage_path) -> None:
        """Load the health judge and full Hive Coder as secondary monitoring graphs.

        Both are added to the current worker runtime so they share its EventBus.
        - Health judge: fires every 2 minutes via timer, emits EscalationTickets.
        - Queen (full Hive Coder): two entry points —
            ticket_triage_node fires automatically on WORKER_ESCALATION_TICKET;
            coder_node is the interactive interface when operator connects via Ctrl+Q.

        The queen gets the full hive-tools MCP tool set: read_file, run_command,
        restart_agent, get_agent_session_state, etc. Gap 1 is resolved.

        Works for any agent automatically — no agent-side configuration needed.
        """
        import asyncio
        import json as _json
        from pathlib import Path

        from framework.agents.hive_coder.agent import HiveCoderAgent
        from framework.monitoring import HEALTH_JUDGE_ENTRY_POINT, judge_goal, judge_graph
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.execution_stream import EntryPointSpec
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        try:
            storage_path = Path(storage_path)
            loop = asyncio.get_event_loop()

            # 1. Monitoring tools: health summary, emit ticket, notify operator
            monitoring_registry = ToolRegistry()
            register_worker_monitoring_tools(
                monitoring_registry,
                self.runtime._event_bus,
                storage_path,
                worker_graph_id=self.runtime._graph_id,
            )
            monitoring_tools = list(monitoring_registry.get_tools().values())
            monitoring_executor = monitoring_registry.get_executor()
            monitoring_tool_names = {t.name for t in monitoring_tools}

            # 2. Full Hive Coder setup — loads hive-tools MCP, giving the queen
            #    read_file, write_file, run_command, restart_agent, etc.
            #    mock_mode=True: skip LLM provider init; the queen will use the
            #    worker runtime's LLM when it actually runs.
            self._queen_agent = HiveCoderAgent()
            await loop.run_in_executor(None, lambda: self._queen_agent._setup(mock_mode=True))
            queen_tools_raw = list(self._queen_agent._tool_registry.get_tools().values())
            queen_executor = self._queen_agent._tool_registry.get_executor()
            queen_tool_names = {t.name for t in queen_tools_raw}
            # Only add tools not already on the worker runtime (avoid duplicate schemas)
            existing_tool_names = {t.name for t in self.runtime._tools}
            queen_tools = [t for t in queen_tools_raw if t.name not in existing_tool_names]

            # 3. Merge monitoring + queen tools into the worker runtime so all
            #    secondary graphs (judge, queen) can call them.
            original_executor = self.runtime._tool_executor

            def merged_executor(tool_use):
                if tool_use.name in monitoring_tool_names:
                    return monitoring_executor(tool_use)
                if tool_use.name in queen_tool_names:
                    return queen_executor(tool_use)
                if original_executor is not None:
                    return original_executor(tool_use)
                from framework.llm.provider import ToolResult
                return ToolResult(
                    tool_use_id=tool_use.id,
                    content=_json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
                    is_error=True,
                )

            self.runtime._tools = self.runtime._tools + monitoring_tools + queen_tools
            self.runtime._tool_executor = merged_executor

            # Dispatch add_graph calls to the agent execution loop.
            # add_graph creates asyncio.Tasks for timers and event handlers;
            # these MUST live on the agent loop (where stream.execute runs
            # LLM calls and tool execution), not Textual's UI loop.
            agent_loop = self.chat_repl._agent_loop

            # 4. Load health judge as a secondary graph on the worker runtime
            future = asyncio.run_coroutine_threadsafe(
                self.runtime.add_graph(
                    graph_id="worker_health_judge",
                    graph=judge_graph,
                    goal=judge_goal,
                    entry_points={"health_check": HEALTH_JUDGE_ENTRY_POINT},
                    storage_subpath="graphs/worker_health_judge",
                ),
                agent_loop,
            )
            await asyncio.wrap_future(future)
            self._judge_graph_id = "worker_health_judge"

            # 5. Load full Hive Coder as the queen graph on the worker runtime.
            #    ticket_triage_node handles auto-triage (event-driven, isolated).
            #    coder_node handles interactive investigation (operator via Ctrl+Q).
            queen_entry_points = {
                "ticket_receiver": EntryPointSpec(
                    id="ticket_receiver",
                    name="Ticket Receiver",
                    entry_node="ticket_triage",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["worker_escalation_ticket"],
                        "exclude_own_graph": True,
                    },
                    isolation_level="isolated",
                ),
                "start": EntryPointSpec(
                    id="start",
                    name="Start",
                    entry_node="coder",
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            }
            future = asyncio.run_coroutine_threadsafe(
                self.runtime.add_graph(
                    graph_id="hive_coder_queen",
                    graph=self._queen_agent._graph,
                    goal=self._queen_agent.goal,
                    entry_points=queen_entry_points,
                    storage_subpath="graphs/hive_coder_queen",
                ),
                agent_loop,
            )
            await asyncio.wrap_future(future)
            self._queen_graph_id = "hive_coder_queen"

            self.notify(
                "Health judge + queen monitoring active",
                severity="information",
                timeout=3,
            )
        except Exception as e:
            logging.getLogger("tui.judge").error(
                "Failed to load health monitoring: %s", e, exc_info=True
            )
            self.notify(
                f"Health monitoring unavailable: {e}",
                severity="warning",
                timeout=5,
            )

    def _show_account_selection(self, runner, accounts: list[dict]) -> None:
        """Show the account selection screen and continue loading on selection."""
        from framework.tui.screens.account_selection import AccountSelectionScreen

        def _on_selection(selected: dict | None) -> None:
            if selected is None:
                self.status_bar.set_graph_id("")
                self.notify(
                    "Account selection cancelled. Agent not loaded.",
                    severity="warning",
                    timeout=5,
                )
                return

            # Scope tools to the selected provider
            if runner._configure_for_account:
                runner._configure_for_account(runner, selected)

            # Continue with the rest of agent loading
            self._do_finish_agent_load(runner)

        self.push_screen(AccountSelectionScreen(accounts), callback=_on_selection)

    @work(exclusive=True)
    async def _do_finish_agent_load(self, runner) -> None:
        """Worker wrapper for _finish_agent_load (used by account selection callback)."""
        await self._finish_agent_load(runner)

    def _show_credential_setup(
        self,
        agent_path: str,
        on_cancel: object | None = None,
        credential_error: Exception | None = None,
    ) -> None:
        """Show the credential setup screen for an agent with missing credentials.

        Args:
            agent_path: Path to the agent that needs credentials.
            on_cancel: Callable to invoke if the user skips/cancels setup.
            credential_error: The CredentialError from validation (carries
                ``failed_cred_names`` for both missing and invalid creds).
        """
        from framework.credentials.validation import build_setup_session_from_error
        from framework.tui.screens.credential_setup import CredentialSetupScreen

        session = build_setup_session_from_error(
            credential_error or Exception("unknown"),
            agent_path=agent_path,
        )

        if not session.missing:
            self.status_bar.set_graph_id("")
            error_msg = str(credential_error) if credential_error else ""
            if "not connected" in error_msg or "Aden" in error_msg:
                self.notify(
                    "ADEN_API_KEY is set but OAuth integrations "
                    "are not connected. Visit hive.adenhq.com "
                    "to connect them, then reload the agent.",
                    severity="warning",
                    timeout=15,
                )
            else:
                self.notify(
                    "Credential error but no missing credentials "
                    "detected. Run 'hive setup-credentials' "
                    "from the terminal.",
                    severity="error",
                    timeout=10,
                )
            if callable(on_cancel):
                on_cancel()
            return

        def _on_result(result: bool | None) -> None:
            if result is True:
                # Credentials saved — retry loading the agent
                self._do_load_agent(agent_path)
            else:
                self.status_bar.set_graph_id("")
                self.notify(
                    "Credential setup skipped. Agent not loaded.",
                    severity="warning",
                    timeout=5,
                )
                if callable(on_cancel):
                    on_cancel()

        self.push_screen(CredentialSetupScreen(session), callback=_on_result)

    # -- Agent picker --

    def _show_agent_picker_initial(self) -> None:
        """Show the agent picker on initial startup (no agent loaded)."""
        from framework.tui.screens.agent_picker import AgentPickerScreen, discover_agents

        agents = discover_agents()
        if not agents:
            self.notify("No agents found in exports/ or examples/", severity="error", timeout=5)
            self.set_timer(2.0, self.exit)
            return

        def _on_initial_pick(result: str | None) -> None:
            if result is None:
                self.exit()
                return
            self._do_load_agent(result)

        self.push_screen(AgentPickerScreen(agents), callback=_on_initial_pick)

    def action_show_agent_picker(self) -> None:
        """Open the agent picker (Ctrl+A or /agents)."""
        from framework.tui.screens.agent_picker import AgentPickerScreen, discover_agents

        agents = discover_agents()
        if not agents:
            self.notify("No agents found", severity="error", timeout=5)
            return

        def _on_pick(result: str | None) -> None:
            if result is not None:
                self._do_load_agent(result)

        self.push_screen(AgentPickerScreen(agents), callback=_on_pick)

    @work(exclusive=True)
    async def _do_load_agent(self, agent_path: str) -> None:
        """Worker wrapper for _load_and_switch_agent."""
        await self._load_and_switch_agent(agent_path)

    # -- Escalation to Hive Coder --

    @work(exclusive=True, group="escalation")
    async def _do_escalate_to_coder(
        self,
        reason: str = "",
        context: str = "",
        node_id: str = "",
    ) -> None:
        """Push current agent onto stack and load hive_coder."""
        from pathlib import Path

        from framework.credentials.models import CredentialError
        from framework.runner import AgentRunner
        from framework.tools.session_graph_tools import register_graph_tools

        if self.runtime is None:
            self.notify("No active agent to escalate from", severity="error")
            return

        # 1. Save current state (do NOT cleanup — worker stays alive)
        saved = {
            "runner": self._runner,
            "runtime": self.runtime,
            "blocked_node_id": node_id,
        }
        self._escalation_stack.append(saved)

        # Unsubscribe from worker events
        if hasattr(self, "_subscription_id"):
            try:
                self.runtime.unsubscribe_from_events(self._subscription_id)
            except Exception:
                pass
            del self._subscription_id

        # Remember worker agent path for coder context
        worker_path = ""
        if self._runner and hasattr(self._runner, "agent_path"):
            worker_path = str(self._runner.agent_path.resolve())

        # 2. Remove worker widgets (they get destroyed)
        workspace = self.query_one("#agent-workspace", Horizontal)
        for child in list(workspace.children):
            child.remove()
        self.graph_view = None
        self.chat_repl = None

        # 3. Show loading state
        self.status_bar.set_graph_id("Loading Hive Coder...")
        self.notify("Escalating to Hive Coder...", timeout=3)

        # 4. Load hive_coder
        framework_agents_dir = Path(__file__).resolve().parent.parent / "agents"
        hive_coder_path = framework_agents_dir / "hive_coder"

        import asyncio
        import functools

        loop = asyncio.get_event_loop()
        try:
            load_fn = functools.partial(
                AgentRunner.load,
                str(hive_coder_path),
                model=self._model,
                interactive=False,
            )
            runner = await loop.run_in_executor(None, load_fn)
            if runner._agent_runtime is None:
                await loop.run_in_executor(None, runner._setup)

            coder_runtime = runner._agent_runtime
            coder_runtime._graph_id = "hive_coder"
            coder_runtime._active_graph_id = "hive_coder"

            # Register graph lifecycle tools
            register_graph_tools(runner._tool_registry, coder_runtime)
            coder_runtime._tools = list(runner._tool_registry.get_tools().values())
            coder_runtime._tool_executor = runner._tool_registry.get_executor()

            self._runner = runner
            self.runtime = coder_runtime
        except CredentialError as e:
            self.status_bar.set_graph_id("")
            self._show_credential_setup(
                str(hive_coder_path),
                on_cancel=self._restore_from_escalation_stack,
                credential_error=e,
            )
            return
        except Exception as e:
            self.status_bar.set_graph_id("")
            self.notify(f"Failed to load coder: {e}", severity="error", timeout=10)
            self._restore_from_escalation_stack()
            return

        # 5. Mount coder widgets and subscribe
        self._mount_agent_widgets()

        # Start runtime on the agent loop (same pattern as _finish_agent_load)
        if not coder_runtime.is_running:
            try:
                agent_loop = self.chat_repl._agent_loop
                future = asyncio.run_coroutine_threadsafe(
                    coder_runtime.start(), agent_loop
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self.notify(f"Failed to start coder runtime: {e}", severity="error")
                self._restore_from_escalation_stack()
                return

        await self._init_runtime_connection()

        self.status_bar.set_graph_id("hive_coder (escalated)")

        # 6. Auto-trigger coder with escalation context
        escalation_input = self._build_escalation_input(reason, context, worker_path)
        try:
            import asyncio

            entry_points = self.runtime.get_entry_points()
            if entry_points:
                ep = entry_points[0]
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.trigger(
                        entry_point_id=ep.id,
                        input_data={"user_request": escalation_input},
                    ),
                    self.chat_repl._agent_loop,
                )
                exec_id = await asyncio.wrap_future(future)
                self.chat_repl._current_exec_id = exec_id
        except Exception as e:
            self.notify(f"Error starting coder: {e}", severity="error")

        self.notify(
            "Hive Coder loaded. Ctrl+E or /back to return.",
            severity="information",
            timeout=5,
        )
        self.refresh_bindings()

    def _build_escalation_input(self, reason: str, context: str, worker_path: str) -> str:
        """Compose the user_request string for hive_coder."""
        parts = []
        if worker_path:
            parts.append(
                f"Modify the agent at: {worker_path}\n"
                f"Do NOT ask which agent to modify — it is the path above."
            )
        if reason:
            parts.append(f"Problem: {reason}")
        if context:
            parts.append(f"Context:\n{context}")
        if not parts:
            parts.append("The user needs help modifying their agent.")
        return "\n\n".join(parts)

    async def _return_from_escalation(self, summary: str = "") -> None:
        """Pop escalation stack and restore the worker agent."""
        if not self._escalation_stack:
            self.notify("No escalation to return from", severity="warning")
            return

        # 1. Tear down coder
        self._unmount_agent_widgets()
        if self._runner is not None:
            try:
                await self._runner.cleanup_async()
            except Exception:
                pass

        # 2. Restore worker
        saved = self._escalation_stack.pop()
        self._runner = saved["runner"]
        self.runtime = saved["runtime"]

        # 3. Mount fresh widgets for the worker runtime
        self._mount_agent_widgets()
        await self._init_runtime_connection()

        graph_id = self.runtime.graph.id if self.runtime else ""
        self.status_bar.set_graph_id(graph_id)

        # 4. Inject return message to unblock the worker node
        blocked_node_id = saved.get("blocked_node_id", "")
        return_msg = summary or "Coder session completed. Continuing."
        if blocked_node_id:
            try:
                import asyncio

                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.inject_input(blocked_node_id, return_msg),
                    self.chat_repl._agent_loop,
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self.notify(
                    f"Could not resume worker: {e}",
                    severity="warning",
                    timeout=5,
                )

        # 5. Show return in chat (deferred — widgets need a tick to mount)
        def _show_return():
            if self.chat_repl:
                self.chat_repl._write_history("[bold cyan]Returned from Hive Coder.[/bold cyan]")
                if summary:
                    self.chat_repl._write_history(f"[dim]{summary}[/dim]")

        self.call_later(_show_return)
        self.notify("Returned to worker agent", severity="information", timeout=3)
        self.refresh_bindings()

    def _restore_from_escalation_stack(self) -> None:
        """Emergency restore when coder loading fails."""
        if not self._escalation_stack:
            return
        saved = self._escalation_stack.pop()
        self._runner = saved["runner"]
        self.runtime = saved["runtime"]
        self._mount_agent_widgets()
        self.call_later(self._init_runtime_connection)

    # -- Logging --

    def _setup_logging_queue(self) -> None:
        """Setup a thread-safe queue for logs."""
        try:
            import queue
            from logging.handlers import QueueHandler

            self.log_queue = queue.Queue()
            self.queue_handler = QueueHandler(self.log_queue)
            self.queue_handler.setLevel(logging.INFO)

            # Get root logger
            root_logger = logging.getLogger()

            # Remove ALL existing handlers to prevent stdout output
            # This is critical - StreamHandlers cause text to appear in header
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

            # Add ONLY our queue handler
            root_logger.addHandler(self.queue_handler)
            root_logger.setLevel(logging.INFO)

            # Suppress LiteLLM logging completely
            litellm_logger = logging.getLogger("LiteLLM")
            litellm_logger.setLevel(logging.CRITICAL)  # Only show critical errors
            litellm_logger.propagate = False  # Don't propagate to root logger

            # Start polling
            self.set_interval(0.1, self._poll_logs)
        except Exception:
            pass

    def _poll_logs(self) -> None:
        """Poll the log queue and update UI."""
        if not self.is_ready or self.chat_repl is None:
            return

        try:
            while not self.log_queue.empty():
                record = self.log_queue.get_nowait()
                # Filter out framework/library logs
                if record.name.startswith(("textual", "LiteLLM", "litellm")):
                    continue

                self.chat_repl.write_python_log(record)
        except Exception:
            pass

    # -- Runtime event routing --

    _EVENT_TYPES = [
        EventType.LLM_TEXT_DELTA,
        EventType.CLIENT_OUTPUT_DELTA,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.EXECUTION_STARTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.NODE_LOOP_STARTED,
        EventType.NODE_LOOP_ITERATION,
        EventType.NODE_LOOP_COMPLETED,
        EventType.CLIENT_INPUT_REQUESTED,
        EventType.NODE_STALLED,
        EventType.GOAL_PROGRESS,
        EventType.GOAL_ACHIEVED,
        EventType.CONSTRAINT_VIOLATION,
        EventType.STATE_CHANGED,
        EventType.NODE_INPUT_BLOCKED,
        EventType.CONTEXT_COMPACTED,
        EventType.NODE_INTERNAL_OUTPUT,
        EventType.JUDGE_VERDICT,
        EventType.OUTPUT_KEY_SET,
        EventType.NODE_RETRY,
        EventType.EDGE_TRAVERSED,
        EventType.EXECUTION_PAUSED,
        EventType.EXECUTION_RESUMED,
        EventType.ESCALATION_REQUESTED,
        EventType.WORKER_ESCALATION_TICKET,
        EventType.QUEEN_INTERVENTION_REQUESTED,
    ]

    _LOG_PANE_EVENTS = frozenset(_EVENT_TYPES) - {
        EventType.LLM_TEXT_DELTA,
        EventType.CLIENT_OUTPUT_DELTA,
    }

    async def _init_runtime_connection(self) -> None:
        """Subscribe to runtime events with an async handler."""
        try:
            self._subscription_id = self.runtime.subscribe_to_events(
                event_types=self._EVENT_TYPES,
                handler=self._handle_event,
            )
        except Exception:
            pass

    async def _handle_event(self, event: AgentEvent) -> None:
        """Bridge events to Textual's main thread for UI updates.

        Events may arrive from the agent-execution thread (normal LLM/tool
        work) or from the Textual thread itself (e.g. webhook server events).
        ``call_from_thread`` requires a *different* thread, so we detect
        which thread we're on and act accordingly.
        """
        try:
            if threading.get_ident() == self._thread_id:
                # Already on Textual's thread — call directly.
                self._route_event(event)
            else:
                # On a different thread — bridge via call_from_thread.
                self.call_from_thread(self._route_event, event)
        except Exception as e:
            logging.getLogger("tui.events").error(
                "call_from_thread failed for %s (node=%s): %s",
                event.type.value,
                event.node_id or "?",
                e,
            )

    def _route_event(self, event: AgentEvent) -> None:
        """Route incoming events to widgets. Runs on Textual's main thread."""
        if not self.is_ready or self.chat_repl is None:
            return

        try:
            et = event.type

            # --- Multi-graph filtering ---
            # If the event has a graph_id and it's not the active graph,
            # show a notification for important events and drop the rest.
            if event.graph_id is not None and event.graph_id != self.runtime.active_graph_id:
                if et == EventType.CLIENT_INPUT_REQUESTED:
                    self.notify(
                        f"[bold]{event.graph_id}[/bold] is waiting for input",
                        severity="warning",
                        timeout=10,
                    )
                elif et == EventType.EXECUTION_FAILED:
                    error = event.data.get("error", "Unknown error")[:60]
                    self.notify(
                        f"[bold red]{event.graph_id}[/bold red] failed: {error}",
                        severity="error",
                        timeout=10,
                    )
                elif et == EventType.EXECUTION_COMPLETED:
                    self.notify(
                        f"[bold green]{event.graph_id}[/bold green] completed",
                        severity="information",
                        timeout=5,
                    )
                elif et == EventType.WORKER_ESCALATION_TICKET:
                    # Judge ticket from background graph — still update status bar
                    ticket = event.data.get("ticket", {})
                    severity = ticket.get("severity", "")
                    if severity:
                        self.status_bar.set_node_detail(f"judge: {severity} ticket")
                elif et == EventType.QUEEN_INTERVENTION_REQUESTED:
                    # Always surface queen interventions regardless of active graph
                    self._handle_queen_intervention(event.data)
                # All other background events are silently dropped (visible in logs)
                return

            # --- Chat REPL events ---
            if et in (EventType.LLM_TEXT_DELTA, EventType.CLIENT_OUTPUT_DELTA):
                self.chat_repl.handle_text_delta(
                    event.data.get("content", ""),
                    event.data.get("snapshot", ""),
                )
            elif et == EventType.TOOL_CALL_STARTED:
                self.chat_repl.handle_tool_started(
                    event.data.get("tool_name", "unknown"),
                    event.data.get("tool_input", {}),
                )
            elif et == EventType.TOOL_CALL_COMPLETED:
                self.chat_repl.handle_tool_completed(
                    event.data.get("tool_name", "unknown"),
                    event.data.get("result", ""),
                    event.data.get("is_error", False),
                )
            elif et == EventType.EXECUTION_COMPLETED:
                self.chat_repl.handle_execution_completed(event.data.get("output", {}))
            elif et == EventType.EXECUTION_FAILED:
                self.chat_repl.handle_execution_failed(event.data.get("error", "Unknown error"))
            elif et == EventType.CLIENT_INPUT_REQUESTED:
                self.chat_repl.handle_input_requested(
                    event.node_id or event.data.get("node_id", ""),
                    graph_id=event.graph_id,
                )
            elif et == EventType.ESCALATION_REQUESTED:
                self.chat_repl.handle_escalation_requested(event.data)
                self._do_escalate_to_coder(
                    reason=event.data.get("reason", ""),
                    context=event.data.get("context", ""),
                    node_id=event.node_id or "",
                )
            elif et == EventType.WORKER_ESCALATION_TICKET:
                ticket = event.data.get("ticket", {})
                severity = ticket.get("severity", "")
                if severity:
                    self.status_bar.set_node_detail(f"judge: {severity} ticket")
            elif et == EventType.QUEEN_INTERVENTION_REQUESTED:
                self._handle_queen_intervention(event.data)
            elif et == EventType.NODE_LOOP_STARTED:
                self.chat_repl.handle_node_started(event.node_id or "")
            elif et == EventType.NODE_LOOP_ITERATION:
                self.chat_repl.handle_loop_iteration(event.data.get("iteration", 0))
            elif et == EventType.NODE_LOOP_COMPLETED:
                self.chat_repl.handle_node_completed(event.node_id or "")

            # Non-client-facing node output → chat repl
            if et == EventType.NODE_INTERNAL_OUTPUT:
                content = event.data.get("content", "")
                if content.strip():
                    self.chat_repl.handle_internal_output(event.node_id or "", content)

            # Execution paused/resumed → chat repl
            if et == EventType.EXECUTION_PAUSED:
                reason = event.data.get("reason", "")
                self.chat_repl.handle_execution_paused(event.node_id or "", reason)
            elif et == EventType.EXECUTION_RESUMED:
                self.chat_repl.handle_execution_resumed(event.node_id or "")

            # Goal achieved / constraint violation → chat repl
            if et == EventType.GOAL_ACHIEVED:
                self.chat_repl.handle_goal_achieved(event.data)
            elif et == EventType.CONSTRAINT_VIOLATION:
                self.chat_repl.handle_constraint_violation(event.data)

            # --- Graph view events ---
            if self.graph_view is not None:
                if et in (
                    EventType.EXECUTION_STARTED,
                    EventType.EXECUTION_COMPLETED,
                    EventType.EXECUTION_FAILED,
                ):
                    self.graph_view.update_execution(event)

                if et == EventType.NODE_LOOP_STARTED:
                    self.graph_view.handle_node_loop_started(event.node_id or "")
                elif et == EventType.NODE_LOOP_ITERATION:
                    self.graph_view.handle_node_loop_iteration(
                        event.node_id or "",
                        event.data.get("iteration", 0),
                    )
                elif et == EventType.NODE_LOOP_COMPLETED:
                    self.graph_view.handle_node_loop_completed(event.node_id or "")
                elif et == EventType.NODE_STALLED:
                    self.graph_view.handle_stalled(
                        event.node_id or "",
                        event.data.get("reason", ""),
                    )

                if et == EventType.TOOL_CALL_STARTED:
                    self.graph_view.handle_tool_call(
                        event.node_id or "",
                        event.data.get("tool_name", "unknown"),
                        started=True,
                    )
                elif et == EventType.TOOL_CALL_COMPLETED:
                    self.graph_view.handle_tool_call(
                        event.node_id or "",
                        event.data.get("tool_name", "unknown"),
                        started=False,
                    )

                # Edge traversal → graph view
                if et == EventType.EDGE_TRAVERSED:
                    self.graph_view.handle_edge_traversed(
                        event.data.get("source_node", ""),
                        event.data.get("target_node", ""),
                    )

            # --- Status bar events ---
            if et == EventType.EXECUTION_STARTED:
                entry_node = event.data.get("entry_node") or (
                    self.runtime.graph.entry_node if self.runtime else ""
                )
                self.status_bar.set_running(entry_node)
            elif et == EventType.EXECUTION_COMPLETED:
                self.status_bar.set_completed()
            elif et == EventType.EXECUTION_FAILED:
                self.status_bar.set_failed(event.data.get("error", ""))
            elif et == EventType.NODE_LOOP_STARTED:
                nid = event.node_id or ""
                node = self.runtime.graph.get_node(nid)
                name = node.name if node else nid
                self.status_bar.set_active_node(name, "thinking...")
            elif et == EventType.NODE_LOOP_ITERATION:
                self.status_bar.set_node_detail(f"step {event.data.get('iteration', '?')}")
            elif et == EventType.TOOL_CALL_STARTED:
                self.status_bar.set_node_detail(f"{event.data.get('tool_name', '')}...")
            elif et == EventType.TOOL_CALL_COMPLETED:
                self.status_bar.set_node_detail("thinking...")
            elif et == EventType.NODE_STALLED:
                self.status_bar.set_node_detail(f"stalled: {event.data.get('reason', '')}")
            elif et == EventType.CONTEXT_COMPACTED:
                before = event.data.get("usage_before", "?")
                after = event.data.get("usage_after", "?")
                self.status_bar.set_node_detail(f"compacted: {before}% \u2192 {after}%")
            elif et == EventType.JUDGE_VERDICT:
                action = event.data.get("action", "?")
                self.status_bar.set_node_detail(f"judge: {action}")
            elif et == EventType.OUTPUT_KEY_SET:
                key = event.data.get("key", "?")
                self.status_bar.set_node_detail(f"set: {key}")
            elif et == EventType.NODE_RETRY:
                retry = event.data.get("retry_count", "?")
                max_r = event.data.get("max_retries", "?")
                self.status_bar.set_node_detail(f"retry {retry}/{max_r}")
            elif et == EventType.EXECUTION_PAUSED:
                self.status_bar.set_node_detail("paused")
            elif et == EventType.EXECUTION_RESUMED:
                self.status_bar.set_node_detail("resumed")

            # --- Log events (inline in chat) ---
            if et in self._LOG_PANE_EVENTS:
                self.chat_repl.write_log_event(event)
        except Exception as e:
            logging.getLogger("tui.events").error(
                "Route failed for %s (node=%s): %s",
                event.type.value,
                event.node_id or "?",
                e,
                exc_info=True,
            )

    def _handle_queen_intervention(self, data: dict) -> None:
        """Notify the operator of a queen escalation — non-disruptively.

        The worker keeps running. The operator can press Ctrl+Q to switch to
        the queen's graph view for a conversation about the issue.
        """
        severity = data.get("severity", "unknown")
        analysis = data.get("analysis", "(no analysis)")

        severity_markup = {
            "low": "[dim]low[/dim]",
            "medium": "[yellow]medium[/yellow]",
            "high": "[bold red]high[/bold red]",
            "critical": "[bold red]CRITICAL[/bold red]",
        }
        sev_label = severity_markup.get(severity, severity)

        msg = f"Queen escalation ({sev_label}): {analysis}"
        if self._queen_graph_id:
            msg += "\nPress [bold]Ctrl+Q[/bold] to chat with queen."

        textual_severity = "error" if severity in ("high", "critical") else "warning"
        self.notify(msg, severity=textual_severity, timeout=30)

    # -- Actions --

    def action_switch_graph(self, graph_id: str) -> None:
        """Switch the active graph focus in the TUI."""
        if self.runtime is None:
            return
        try:
            self.runtime.active_graph_id = graph_id
        except ValueError:
            self.notify(f"Graph '{graph_id}' not found", severity="error", timeout=3)
            return

        # Update status bar
        self.status_bar.set_graph_id(graph_id)

        # Update graph view
        reg = self.runtime.get_graph_registration(graph_id)
        if reg and self.graph_view:
            self.graph_view.switch_graph(reg.graph)

        # Flush chat streaming state
        if self.chat_repl:
            self.chat_repl.flush_streaming()

        self.notify(f"Switched to graph: {graph_id}", severity="information", timeout=3)

    def save_screenshot(self, filename: str | None = None) -> str:
        """Save a screenshot of the current screen as SVG (viewable in browsers)."""
        from datetime import datetime
        from pathlib import Path

        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tui_screenshot_{timestamp}.svg"

        if not filename.endswith(".svg"):
            filename += ".svg"

        filepath = screenshots_dir / filename

        from framework.tui.widgets.chat_repl import ChatRepl

        try:
            chat_widget = self.query_one(ChatRepl)
        except Exception:
            # No ChatRepl mounted yet
            svg_data = self.export_screenshot()
            filepath.write_text(svg_data, encoding="utf-8")
            return str(filepath)

        original_chat_border = chat_widget.styles.border_left
        chat_widget.styles.border_left = ("none", "transparent")

        input_widgets = self.query("ChatTextArea")
        original_input_borders = []
        for input_widget in input_widgets:
            original_input_borders.append(input_widget.styles.border)
            input_widget.styles.border = ("none", "transparent")

        try:
            svg_data = self.export_screenshot()
            filepath.write_text(svg_data, encoding="utf-8")
        finally:
            chat_widget.styles.border_left = original_chat_border
            for i, input_widget in enumerate(input_widgets):
                input_widget.styles.border = original_input_borders[i]

        return str(filepath)

    def action_screenshot(self) -> None:
        """Take a screenshot (bound to Ctrl+S)."""
        try:
            filepath = self.save_screenshot()
            self.notify(
                f"Screenshot saved: {filepath} (SVG - open in browser)",
                severity="information",
                timeout=5,
            )
        except Exception as e:
            self.notify(f"Screenshot failed: {e}", severity="error", timeout=5)

    def action_toggle_logs(self) -> None:
        """Toggle inline log display in chat (bound to Ctrl+L)."""
        if self.chat_repl is None:
            return
        self.chat_repl.toggle_logs()
        mode = "ON" if self.chat_repl._show_logs else "OFF"
        self.notify(f"Logs {mode}", severity="information", timeout=2)

    def action_pause_execution(self) -> None:
        """Immediately pause execution by cancelling task (bound to Ctrl+Z)."""
        if self.chat_repl is None or self.runtime is None:
            return
        try:
            if not self.chat_repl._current_exec_id:
                self.notify(
                    "No active execution to pause",
                    severity="information",
                    timeout=3,
                )
                return

            task_cancelled = False
            all_streams = []
            active_reg = self.runtime.get_graph_registration(self.runtime.active_graph_id)
            if active_reg:
                all_streams.extend(active_reg.streams.values())
            for gid in self.runtime.list_graphs():
                if gid == self.runtime.active_graph_id:
                    continue
                reg = self.runtime.get_graph_registration(gid)
                if reg:
                    all_streams.extend(reg.streams.values())

            for stream in all_streams:
                exec_id = self.chat_repl._current_exec_id
                task = stream._execution_tasks.get(exec_id)
                if task and not task.done():
                    task.cancel()
                    task_cancelled = True
                    self.notify(
                        "Execution paused - state saved",
                        severity="information",
                        timeout=3,
                    )
                    break

            if not task_cancelled:
                self.notify(
                    "Execution already completed",
                    severity="information",
                    timeout=2,
                )
        except Exception as e:
            self.notify(
                f"Error pausing execution: {e}",
                severity="error",
                timeout=5,
            )

    async def action_show_sessions(self) -> None:
        """Show sessions list (bound to Ctrl+R)."""
        if self.chat_repl is None:
            return
        try:
            await self.chat_repl._submit_input("/sessions")
        except Exception:
            self.notify(
                "Use /sessions command to see all sessions",
                severity="information",
                timeout=3,
            )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Control which bindings are shown in the footer.

        Both escalate_to_coder and return_from_coder are bound to Ctrl+E.
        check_action toggles which one is active based on escalation state,
        so the footer shows "Coder" or "← Back" accordingly.
        connect_to_queen is only shown when a queen monitoring graph is active.
        """
        if action == "escalate_to_coder":
            return not self._escalation_stack
        if action == "return_from_coder":
            return bool(self._escalation_stack)
        if action == "connect_to_queen":
            return bool(self._queen_graph_id and self.runtime is not None)
        return True

    def action_connect_to_queen(self) -> None:
        """Toggle between worker and queen graph views (Ctrl+Q)."""
        if not self._queen_graph_id:
            self.notify("No queen monitoring active", severity="warning", timeout=3)
            return
        # Toggle: if already on queen, switch back to worker
        if self.runtime and self.runtime.active_graph_id == self._queen_graph_id:
            self.action_switch_graph(self.runtime.graph_id)
        else:
            self.action_switch_graph(self._queen_graph_id)

    def action_escalate_to_coder(self) -> None:
        """Escalate to Hive Coder (bound to Ctrl+E)."""
        if self.runtime is None:
            self.notify("No active agent to escalate from", severity="error")
            return
        # _do_escalate_to_coder is already @work-decorated; calling it starts the worker.
        self._do_escalate_to_coder(reason="User-initiated escalation")

    async def action_return_from_coder(self) -> None:
        """Return from Hive Coder to worker agent (Ctrl+E toggles)."""
        await self._return_from_escalation()

    async def on_unmount(self) -> None:
        """Cleanup on app shutdown - cancel execution which will save state."""
        self.is_ready = False

        # Cancel any active execution
        try:
            import asyncio

            if self.chat_repl and self.chat_repl._current_exec_id and self.runtime:
                all_streams = []
                for gid in self.runtime.list_graphs():
                    reg = self.runtime.get_graph_registration(gid)
                    if reg:
                        all_streams.extend(reg.streams.values())
                for stream in all_streams:
                    exec_id = self.chat_repl._current_exec_id
                    task = stream._execution_tasks.get(exec_id)
                    if task and not task.done():
                        task.cancel()
                        try:
                            await asyncio.wait_for(task, timeout=5.0)
                        except (TimeoutError, asyncio.CancelledError):
                            pass
                        except Exception:
                            pass
                        break
        except Exception:
            pass

        try:
            if hasattr(self, "_subscription_id") and self.runtime:
                self.runtime.unsubscribe_from_events(self._subscription_id)
        except Exception:
            pass
        try:
            if hasattr(self, "queue_handler"):
                logging.getLogger().removeHandler(self.queue_handler)
        except Exception:
            pass
