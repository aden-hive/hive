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
        self._judge_task = None   # concurrent.futures.Future for the judge loop
        self._queen_task = None   # concurrent.futures.Future for the queen loop
        self._queen_executor = None  # GraphExecutor for queen input injection
        self._queen_escalation_sub = None  # EventBus subscription for queen

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
        self._stop_health_monitoring()
        self._queen_graph_id = None
        self._judge_graph_id = None

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
        """Start health judge and interactive queen as independent conversations.

        Three-conversation architecture:
        - **Queen**: persistent interactive GraphExecutor (user's primary interface)
        - **Judge**: timer-driven background GraphExecutor (silent monitoring)
        - **Worker**: the existing AgentRuntime (unchanged)

        They share ONLY the EventBus (for communication) and the base
        storage path (so the judge can read worker logs).  Nothing else
        is shared — no state manager, no session store, no tool merging
        into the worker runtime.  The worker is completely untouched.
        """
        import asyncio
        from pathlib import Path

        from framework.graph.executor import GraphExecutor
        from framework.monitoring import judge_goal, judge_graph
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime
        from framework.runtime.event_bus import EventType as _ET
        from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        log = logging.getLogger("tui.judge")

        try:
            storage_path = Path(storage_path)
            event_bus = self.runtime._event_bus
            llm = self.runtime._llm
            agent_loop = self.chat_repl._agent_loop

            # 1. Monitoring tools (health summary, emit ticket, notify operator).
            #    Registered on a standalone registry — NOT merged into the worker.
            monitoring_registry = ToolRegistry()
            register_worker_monitoring_tools(
                monitoring_registry,
                event_bus,
                storage_path,
                worker_graph_id=self.runtime._graph_id,
            )

            # 2. Storage dirs — under worker's base path but completely owned
            #    by the judge/queen.  Worker never writes here.
            judge_dir = storage_path / "graphs" / "worker_health_judge" / "session"
            judge_dir.mkdir(parents=True, exist_ok=True)
            queen_dir = storage_path / "graphs" / "queen" / "session"
            queen_dir.mkdir(parents=True, exist_ok=True)

            # ---------------------------------------------------------------
            # 3. Health judge — background task, fires every 2 minutes.
            # ---------------------------------------------------------------
            judge_runtime = Runtime(storage_path / "graphs" / "worker_health_judge")
            monitoring_tools = list(monitoring_registry.get_tools().values())
            monitoring_executor = monitoring_registry.get_executor()

            async def _judge_loop():
                interval = 120  # seconds
                first = True
                while True:
                    if not first:
                        await asyncio.sleep(interval)
                    first = False
                    try:
                        executor = GraphExecutor(
                            runtime=judge_runtime,
                            llm=llm,
                            tools=monitoring_tools,
                            tool_executor=monitoring_executor,
                            event_bus=event_bus,
                            stream_id="worker_health_judge",
                            storage_path=judge_dir,
                            loop_config=judge_graph.loop_config,
                        )
                        await executor.execute(
                            graph=judge_graph,
                            goal=judge_goal,
                            input_data={
                                "event": {"source": "timer", "reason": "scheduled"},
                            },
                            session_state={"resume_session_id": "persistent"},
                        )
                    except Exception:
                        log.error("Health judge tick failed", exc_info=True)

            self._judge_task = asyncio.run_coroutine_threadsafe(
                _judge_loop(), agent_loop,
            )
            self._judge_graph_id = "worker_health_judge"

            # ---------------------------------------------------------------
            # 4. Queen — persistent interactive conversation.
            #    Runs a continuous event_loop node that is the user's
            #    primary interface.  Has lifecycle tools to control the
            #    worker.  Escalation tickets from the judge are injected
            #    as messages into this conversation.
            # ---------------------------------------------------------------
            import framework.agents.hive_coder as _hive_coder_pkg
            from framework.agents.hive_coder.agent import queen_goal, queen_graph

            # Queen gets lifecycle tools, monitoring tools, AND coding tools
            # from the hive_coder's coder-tools MCP server.  This spawns a
            # separate MCP process so the queen can read/write files, run
            # commands, discover tools, etc. independently of the worker.
            queen_registry = ToolRegistry()

            # Coding tools from hive_coder's MCP config (coder_tools_server).
            hive_coder_dir = Path(_hive_coder_pkg.__file__).parent
            mcp_config = hive_coder_dir / "mcp_servers.json"
            if mcp_config.exists():
                try:
                    queen_registry.load_mcp_config(mcp_config)
                    log.info("Queen: loaded MCP config from %s", mcp_config)
                except Exception:
                    log.warning("Queen: MCP config failed to load", exc_info=True)

            register_queen_lifecycle_tools(
                queen_registry,
                worker_runtime=self.runtime,
                event_bus=event_bus,
                storage_path=storage_path,
            )
            register_worker_monitoring_tools(
                queen_registry,
                event_bus,
                storage_path,
                stream_id="queen",
                worker_graph_id=self.runtime._graph_id,
            )
            queen_tools = list(queen_registry.get_tools().values())
            queen_tool_executor = queen_registry.get_executor()

            # Build worker identity to inject into the queen's system prompt.
            # This must be in the system prompt (not input_data) because
            # persistent sessions restore the old conversation and skip
            # _build_initial_message — the queen would lose context.
            worker_graph_id = self.runtime._graph_id
            worker_goal_name = getattr(self.runtime.goal, "name", worker_graph_id)
            worker_goal_desc = getattr(self.runtime.goal, "description", "")
            worker_identity = (
                f"\n\n# Current Session\n"
                f"Worker agent: {worker_graph_id}\n"
                f"Goal: {worker_goal_name}\n"
            )
            if worker_goal_desc:
                worker_identity += f"Description: {worker_goal_desc}\n"
            worker_identity += "Status at session start: idle (not started)."

            # Adjust queen graph: filter tools to what's registered and
            # append worker identity to the system prompt.
            registered_tool_names = set(queen_registry.get_tools().keys())
            _orig_queen_node = queen_graph.nodes[0]
            declared_tools = _orig_queen_node.tools or []
            available_tools = [t for t in declared_tools if t in registered_tool_names]

            node_updates: dict = {}
            if set(available_tools) != set(declared_tools):
                missing = sorted(set(declared_tools) - registered_tool_names)
                log.warning("Queen: tools not available (MCP may have failed): %s", missing)
                node_updates["tools"] = available_tools
            # Always inject worker identity into system prompt.
            base_prompt = _orig_queen_node.system_prompt or ""
            node_updates["system_prompt"] = base_prompt + worker_identity

            adjusted_node = _orig_queen_node.model_copy(update=node_updates)
            queen_graph = queen_graph.model_copy(update={"nodes": [adjusted_node]})

            queen_runtime = Runtime(storage_path / "graphs" / "queen")

            async def _queen_loop():
                try:
                    executor = GraphExecutor(
                        runtime=queen_runtime,
                        llm=llm,
                        tools=queen_tools,
                        tool_executor=queen_tool_executor,
                        event_bus=event_bus,
                        stream_id="queen",
                        storage_path=queen_dir,
                        loop_config=queen_graph.loop_config,
                    )
                    self._queen_executor = executor
                    log.info(
                        "Queen starting with %d tools: %s",
                        len(queen_tools),
                        [t.name for t in queen_tools],
                    )
                    # The queen's event_loop node runs forever (continuous mode).
                    # It blocks on _await_user_input() after each LLM turn,
                    # and input is injected via executor.node_registry["queen"].inject_event().
                    result = await executor.execute(
                        graph=queen_graph,
                        goal=queen_goal,
                        input_data={"greeting": "Session started."},
                        session_state={"resume_session_id": "persistent"},
                    )
                    # Should never reach here — queen is forever-alive.
                    log.warning(
                        "Queen executor returned (should be forever-alive): %s",
                        result,
                    )
                except Exception:
                    log.error("Queen conversation crashed", exc_info=True)
                finally:
                    self._queen_executor = None

            self._queen_task = asyncio.run_coroutine_threadsafe(
                _queen_loop(), agent_loop,
            )
            self._queen_graph_id = "queen"

            # Wire queen injection callback into ChatRepl so user input
            # is routed to the queen by default.
            async def _inject_queen(content: str) -> bool:
                """Inject user input into the queen's active node."""
                executor = self._queen_executor
                if executor is None:
                    return False
                node = executor.node_registry.get("queen")
                if node is not None and hasattr(node, "inject_event"):
                    await node.inject_event(content)
                    return True
                return False

            self.chat_repl._queen_inject_callback = _inject_queen

            # Judge escalation → inject into queen conversation as a message.
            async def _on_escalation(event):
                ticket = event.data.get("ticket", {})
                executor = self._queen_executor
                if executor is None:
                    log.warning("Escalation received but queen executor is None")
                    return
                node = executor.node_registry.get("queen")
                if node is not None and hasattr(node, "inject_event"):
                    import json as _json
                    msg = (
                        "[ESCALATION TICKET from Health Judge]\n"
                        + _json.dumps(ticket, indent=2, ensure_ascii=False)
                    )
                    await node.inject_event(msg)
                else:
                    log.warning("Escalation received but queen node not ready for injection")

            self._queen_escalation_sub = event_bus.subscribe(
                event_types=[_ET.WORKER_ESCALATION_TICKET],
                handler=_on_escalation,
            )

            self.notify(
                "Queen + health judge active",
                severity="information",
                timeout=3,
            )
        except Exception as e:
            log.error("Failed to load health monitoring: %s", e, exc_info=True)
            self.notify(
                f"Health monitoring unavailable: {e}",
                severity="warning",
                timeout=5,
            )

    def _stop_health_monitoring(self) -> None:
        """Cancel judge task, queen task, and subscriptions from a prior load."""
        if self._judge_task is not None:
            self._judge_task.cancel()
            self._judge_task = None
        if self._queen_task is not None:
            self._queen_task.cancel()
            self._queen_task = None
        self._queen_executor = None
        if self._queen_escalation_sub is not None:
            try:
                event_bus = self.runtime._event_bus if self.runtime else None
                if event_bus:
                    event_bus.unsubscribe(self._queen_escalation_sub)
            except Exception:
                pass
            self._queen_escalation_sub = None

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
            self._handle_picker_result(result)

        # Show Get Started tab on initial launch
        self.push_screen(
            AgentPickerScreen(agents, show_get_started=True),
            callback=_on_initial_pick,
        )

    def _handle_picker_result(self, result: str) -> None:
        """Handle the result from the agent picker, including Get Started actions."""
        if result.startswith("action:"):
            action = result.removeprefix("action:")
            if action == "run_examples":
                # Switch to Examples tab by re-opening picker focused on examples
                self._show_agent_picker_tab("examples")
            elif action == "run_existing":
                # Switch to Your Agents tab
                self._show_agent_picker_tab("your-agents")
            elif action == "build_edit":
                # Launch agent builder guidance
                self._show_build_edit_message()
        else:
            # Regular agent path - load it
            self._do_load_agent(result)

    def _show_agent_picker_tab(self, tab_id: str) -> None:
        """Show the agent picker focused on a specific tab (no Get Started)."""
        from framework.tui.screens.agent_picker import AgentPickerScreen, discover_agents

        agents = discover_agents()
        if not agents:
            self.notify("No agents found", severity="error", timeout=5)
            return

        def _on_pick(result: str | None) -> None:
            if result is None:
                self.exit()
                return
            if result.startswith("action:"):
                # Shouldn't happen but handle gracefully
                self._handle_picker_result(result)
            else:
                self._do_load_agent(result)

        screen = AgentPickerScreen(agents, show_get_started=False)

        def _focus_tab() -> None:
            try:
                tabbed = screen.query_one(
                    "TabbedContent", expect_type=type(screen.query_one("TabbedContent"))
                )
                tabbed.active = tab_id
            except Exception:
                pass

        self.push_screen(screen, callback=_on_pick)
        self.call_later(_focus_tab)

    def _show_build_edit_message(self) -> None:
        """Show guidance for building or editing agents."""
        self.notify(
            "To build or edit agents, use 'hive build' from the terminal "
            "or run Claude Code with the /hive skill.",
            severity="information",
            timeout=10,
        )
        # Re-show picker so user can still select an agent
        self._show_agent_picker_initial()

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

            # --- Judge monitoring filter ---
            # The judge runs as a silent background task.  Only surface
            # escalation ticket events on the status bar; everything else
            # (LLM deltas, tool calls, node iterations) goes to logs only.
            if event.stream_id == "worker_health_judge":
                if et == EventType.WORKER_ESCALATION_TICKET:
                    ticket = event.data.get("ticket", {})
                    severity = ticket.get("severity", "")
                    if severity:
                        self.status_bar.set_node_detail(f"judge: {severity} ticket")
                # All judge events → logs only, not displayed.
                return

            # --- Queen-primary event routing ---
            # When the queen is active, queen events go to chat display
            # and worker events are handled specially.
            _queen_active = self._queen_executor is not None

            if _queen_active:
                # Queen events (stream_id="queen") → display in chat
                if event.stream_id == "queen":
                    if et == EventType.QUEEN_INTERVENTION_REQUESTED:
                        self._handle_queen_intervention(event.data)
                        return
                    # Tag streaming source and active node so labels resolve
                    # correctly even when worker events interleave.
                    self.chat_repl._streaming_source = "queen"
                    if event.node_id:
                        self.chat_repl._active_node_id = event.node_id
                    # Queen events fall through to the chat handlers below.

                # Worker events (from AgentRuntime, graph_id set) when queen is primary
                elif event.graph_id is not None:
                    if et == EventType.CLIENT_INPUT_REQUESTED:
                        # Worker asking for input — set override in ChatRepl
                        self.chat_repl.handle_worker_input_requested(
                            event.node_id or event.data.get("node_id", ""),
                            graph_id=event.graph_id,
                        )
                        return
                    elif et == EventType.EXECUTION_COMPLETED:
                        # Inject status into queen conversation
                        self._inject_worker_status_into_queen(
                            "Worker execution completed successfully."
                        )
                        return
                    elif et == EventType.EXECUTION_FAILED:
                        error = event.data.get("error", "Unknown error")[:200]
                        self._inject_worker_status_into_queen(
                            f"Worker execution failed: {error}"
                        )
                        return
                    elif et in (
                        EventType.LLM_TEXT_DELTA,
                        EventType.CLIENT_OUTPUT_DELTA,
                        EventType.TOOL_CALL_STARTED,
                        EventType.TOOL_CALL_COMPLETED,
                    ):
                        # Let worker client-facing output and tool events
                        # through so the user can see what the worker is
                        # doing/asking.  Clear queen streaming source and
                        # update the active node so labels resolve correctly.
                        self.chat_repl._streaming_source = None
                        if event.node_id:
                            self.chat_repl._active_node_id = event.node_id
                        # Fall through to the standard chat handlers below.
                    else:
                        # All other worker events while queen is active → logs only
                        return

            # --- Multi-graph filtering (non-queen mode) ---
            # If the event has a graph_id and it's not the active graph,
            # show a notification for important events and drop the rest.
            if not _queen_active and event.graph_id is not None and event.graph_id != self.runtime.active_graph_id:
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
            # Map of external node IDs (queen, judge) to display names.
            _ext_names = {"queen": "Queen"}

            if et == EventType.EXECUTION_STARTED:
                entry_node = event.data.get("entry_node") or (
                    self.runtime.graph.entry_node if self.runtime else ""
                )
                entry_node = _ext_names.get(entry_node, entry_node)
                self.status_bar.set_running(entry_node)
            elif et == EventType.EXECUTION_COMPLETED:
                self.status_bar.set_completed()
            elif et == EventType.EXECUTION_FAILED:
                self.status_bar.set_failed(event.data.get("error", ""))
            elif et == EventType.NODE_LOOP_STARTED:
                nid = event.node_id or ""
                node = self.runtime.graph.get_node(nid)
                name = node.name if node else _ext_names.get(nid, nid)
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

    def _inject_worker_status_into_queen(self, message: str) -> None:
        """Inject a worker status update into the queen's conversation."""
        import asyncio as _aio

        executor = self._queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

        agent_loop = getattr(self.chat_repl, "_agent_loop", None)
        if agent_loop is None:
            return

        status_msg = f"[WORKER STATUS UPDATE]\n{message}"
        _aio.run_coroutine_threadsafe(node.inject_event(status_msg), agent_loop)

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

        # Stop health monitoring (judge + queen)
        try:
            self._stop_health_monitoring()
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
