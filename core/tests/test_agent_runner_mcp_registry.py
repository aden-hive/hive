"""Tests for AgentRunner MCP registry integration."""

from pathlib import Path

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec
from framework.runner.runner import AgentRunner


def _make_graph() -> GraphSpec:
    return GraphSpec(
        id="test-graph",
        goal_id="goal-1",
        entry_node="start",
        terminal_nodes=["start"],
        nodes=[NodeSpec(id="start", name="Start", description="Start node")],
        edges=[],
    )


class _FakeRegistry:
    def __init__(self, returned_configs):
        self._returned_configs = returned_configs
        self.initialize_calls = 0
        self.loaded_paths: list[Path] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def load_agent_selection(self, agent_path: Path):
        self.loaded_paths.append(agent_path)
        return list(self._returned_configs)


def test_agent_runner_loads_registry_selected_servers(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text('{"include": ["jira"]}', encoding="utf-8")

    fake_registry = _FakeRegistry(
        [
            {
                "name": "jira",
                "transport": "http",
                "url": "http://localhost:4010",
                "headers": {},
                "description": "Jira",
            }
        ]
    )
    registered: list[dict] = []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPRegistry", lambda: fake_registry)
    monkeypatch.setattr(
        "framework.runner.runner.run_preload_validation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(AgentRunner, "_resolve_default_model", staticmethod(lambda: "test-model"))
    monkeypatch.setattr(
        "framework.runner.tool_registry.ToolRegistry.register_mcp_server",
        lambda self, server_config, use_connection_manager=True: (
            registered.append(server_config) or 1
        ),
    )

    AgentRunner(
        agent_path=agent_dir,
        graph=_make_graph(),
        goal=Goal(id="goal-1", name="Goal", description="desc"),
        storage_path=tmp_path / "storage",
        interactive=False,
        skip_credential_validation=True,
    )

    assert fake_registry.initialize_calls == 1
    assert fake_registry.loaded_paths == [agent_dir]
    assert [config["name"] for config in registered] == ["jira"]


def test_agent_runner_skips_registry_when_no_servers_selected(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()

    fake_registry = _FakeRegistry([])
    registered: list[dict] = []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPRegistry", lambda: fake_registry)
    monkeypatch.setattr(
        "framework.runner.runner.run_preload_validation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(AgentRunner, "_resolve_default_model", staticmethod(lambda: "test-model"))
    monkeypatch.setattr(
        "framework.runner.tool_registry.ToolRegistry.register_mcp_server",
        lambda self, server_config, use_connection_manager=True: (
            registered.append(server_config) or 1
        ),
    )

    AgentRunner(
        agent_path=agent_dir,
        graph=_make_graph(),
        goal=Goal(id="goal-1", name="Goal", description="desc"),
        storage_path=tmp_path / "storage",
        interactive=False,
        skip_credential_validation=True,
    )

    assert fake_registry.initialize_calls == 1
    assert fake_registry.loaded_paths == [agent_dir]
    assert registered == []


def test_agent_runner_logs_actual_registry_load_results(tmp_path, monkeypatch):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text('{"include": ["jira", "slack"]}', encoding="utf-8")

    fake_registry = _FakeRegistry(
        [
            {"name": "jira", "transport": "http", "url": "http://localhost:4010"},
            {"name": "slack", "transport": "http", "url": "http://localhost:4020"},
        ]
    )
    log_messages: list[str] = []

    monkeypatch.setattr("framework.runner.mcp_registry.MCPRegistry", lambda: fake_registry)
    monkeypatch.setattr(
        "framework.runner.runner.run_preload_validation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(AgentRunner, "_resolve_default_model", staticmethod(lambda: "test-model"))
    monkeypatch.setattr(
        "framework.runner.tool_registry.ToolRegistry.load_registry_servers",
        lambda self, server_configs: [
            {"server": "jira", "status": "loaded", "tools_loaded": 2, "skipped_reason": None},
            {
                "server": "slack",
                "status": "skipped",
                "tools_loaded": 0,
                "skipped_reason": "registered 0 tools",
            },
        ],
    )
    monkeypatch.setattr(
        "framework.runner.runner.logger.info",
        lambda message, *args: log_messages.append(message % args if args else str(message)),
    )

    AgentRunner(
        agent_path=agent_dir,
        graph=_make_graph(),
        goal=Goal(id="goal-1", name="Goal", description="desc"),
        storage_path=tmp_path / "storage",
        interactive=False,
        skip_credential_validation=True,
    )

    assert any("Loaded 1/2 MCP registry server(s)" in message for message in log_messages)
    assert any("Skipped MCP registry servers" in message for message in log_messages)


def test_agent_runner_survives_malformed_registry_json(tmp_path, monkeypatch):
    """Agent startup must not crash when mcp_registry.json has invalid JSON."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "mcp_registry.json").write_text("{bad json", encoding="utf-8")

    warnings: list[str] = []
    monkeypatch.setattr(
        "framework.runner.runner.run_preload_validation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(AgentRunner, "_resolve_default_model", staticmethod(lambda: "test-model"))
    monkeypatch.setattr(
        "framework.runner.runner.logger.warning",
        lambda message, *args: warnings.append(message % args if args else str(message)),
    )

    AgentRunner(
        agent_path=agent_dir,
        graph=_make_graph(),
        goal=Goal(id="goal-1", name="Goal", description="desc"),
        storage_path=tmp_path / "storage",
        interactive=False,
        skip_credential_validation=True,
    )

    assert any("Failed to load MCP registry servers" in w for w in warnings)
