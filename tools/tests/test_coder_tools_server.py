from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_coder_tools_server():
    module_path = Path(__file__).resolve().parents[1] / "coder_tools_server.py"
    spec = importlib.util.spec_from_file_location("coder_tools_server_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_framework(monkeypatch, tools_by_server: dict[str, list[dict]]) -> None:
    framework_mod = types.ModuleType("framework")
    runner_mod = types.ModuleType("framework.runner")
    mcp_client_mod = types.ModuleType("framework.runner.mcp_client")
    tool_registry_mod = types.ModuleType("framework.runner.tool_registry")

    class FakeMCPServerConfig:
        def __init__(self, **kwargs):
            self.name = kwargs.get("name", "")

    class FakeTool:
        def __init__(self, name: str, description: str = "", input_schema: dict | None = None):
            self.name = name
            self.description = description
            self.input_schema = input_schema or {}

    class FakeMCPClient:
        def __init__(self, config):
            self._server_name = config.name

        def connect(self):
            return None

        def list_tools(self):
            items = tools_by_server.get(self._server_name, [])
            return [
                FakeTool(
                    name=item["name"],
                    description=item.get("description", ""),
                    input_schema=item.get("input_schema", {}),
                )
                for item in items
            ]

        def disconnect(self):
            return None

    class FakeToolRegistry:
        def __init__(self):
            self._tools = {}

        @staticmethod
        def resolve_mcp_stdio_config(config: dict, _config_dir: Path) -> dict:
            return config

        def discover_from_module(self, module_path: Path) -> int:
            spec = importlib.util.spec_from_file_location("fake_agent_tools", module_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._tools.update(getattr(module, "TOOLS", {}))
            return len(getattr(module, "TOOLS", {}))

        def get_tools(self) -> dict:
            return dict(self._tools)

    mcp_client_mod.MCPClient = FakeMCPClient
    mcp_client_mod.MCPServerConfig = FakeMCPServerConfig
    tool_registry_mod.ToolRegistry = FakeToolRegistry

    framework_mod.runner = runner_mod
    runner_mod.mcp_client = mcp_client_mod
    runner_mod.tool_registry = tool_registry_mod

    monkeypatch.setitem(sys.modules, "framework", framework_mod)
    monkeypatch.setitem(sys.modules, "framework.runner", runner_mod)
    monkeypatch.setitem(sys.modules, "framework.runner.mcp_client", mcp_client_mod)
    monkeypatch.setitem(sys.modules, "framework.runner.tool_registry", tool_registry_mod)


def _call_list_agent_tools(mod, **kwargs) -> str:
    tool = mod.mcp._tool_manager._tools["list_agent_tools"]
    return tool.fn(**kwargs)


def test_list_agent_tools_groups_by_provider_and_keeps_uncredentialed(monkeypatch, tmp_path):
    _install_fake_framework(
        monkeypatch,
        tools_by_server={
            "fake-server": [
                {"name": "gmail_list_messages", "description": "Read Gmail"},
                {"name": "calendar_list_events", "description": "Read calendar"},
                {"name": "send_email", "description": "Send email"},
                {"name": "web_scrape", "description": "Scrape a page"},
            ]
        },
    )
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = str(tmp_path)

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps({"fake-server": {"transport": "stdio", "command": "noop", "args": []}}),
        encoding="utf-8",
    )

    raw = _call_list_agent_tools(
        mod,
        server_config_path="mcp_servers.json",
        output_schema="simple",
        group="all",
    )
    data = json.loads(raw)

    providers = data["tools_by_provider"]
    assert "google" in providers
    assert "resend" in providers
    assert "no_provider" in providers

    google_tools = {t["name"] for t in providers["google"]["tools"]}
    assert "gmail_list_messages" in google_tools
    assert "calendar_list_events" in google_tools
    assert "send_email" in google_tools
    assert providers["google"]["authorization"]

    resend_tools = {t["name"] for t in providers["resend"]["tools"]}
    assert resend_tools == {"send_email"}
    assert providers["resend"]["authorization"]

    no_provider_tools = {t["name"] for t in providers["no_provider"]["tools"]}
    assert "web_scrape" in no_provider_tools
    assert providers["no_provider"]["authorization"] == {}


def test_list_agent_tools_provider_filter_and_legacy_prefix_filter(monkeypatch, tmp_path):
    _install_fake_framework(
        monkeypatch,
        tools_by_server={
            "fake-server": [
                {"name": "gmail_list_messages", "description": "Read Gmail"},
                {"name": "web_scrape", "description": "Scrape a page"},
            ]
        },
    )
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = str(tmp_path)

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps({"fake-server": {"transport": "stdio", "command": "noop", "args": []}}),
        encoding="utf-8",
    )

    provider_raw = _call_list_agent_tools(
        mod,
        server_config_path="mcp_servers.json",
        output_schema="simple",
        group="google",
    )
    provider_data = json.loads(provider_raw)
    assert list(provider_data["tools_by_provider"].keys()) == ["google"]
    assert provider_data["all_tool_names"] == ["gmail_list_messages"]

    legacy_raw = _call_list_agent_tools(
        mod,
        server_config_path="mcp_servers.json",
        output_schema="simple",
        group="gmail",
    )
    legacy_data = json.loads(legacy_raw)
    assert list(legacy_data["tools_by_provider"].keys()) == ["google"]
    assert legacy_data["all_tool_names"] == ["gmail_list_messages"]


def test_behavior_validation_errors_rejects_placeholder_prompts_and_empty_work_nodes():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="TODO: Add identity prompt.",
        metadata=SimpleNamespace(
            description="TODO: Add agent description.",
            intro_message="TODO: Add intro message.",
        ),
        goal=SimpleNamespace(
            description="TODO: Describe the goal.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="TODO: Define success criterion.",
                    metric="TODO",
                    target="TODO",
                )
            ],
            constraints=[
                SimpleNamespace(id="c-1", description="TODO: Define constraint."),
            ],
        ),
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="scan",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                description="TODO: Describe what this node does.",
                system_prompt="TODO: Add system prompt for this node.",
                success_criteria="Find files.",
            ),
            SimpleNamespace(
                id="summarize",
                client_facing=False,
                tools=[],
                sub_agents=[],
                description="Summarize the docs.",
                system_prompt="Write condensed markdown summaries.",
                success_criteria="Produce summaries.",
            ),
            SimpleNamespace(
                id="done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert "identity_prompt still contains TODO placeholders" in errors
    assert "metadata.description is blank or still contains TODO placeholders" in errors
    assert "metadata.intro_message is blank or still contains TODO placeholders" in errors
    assert "goal.description is blank or still contains TODO placeholders" in errors
    assert "Success criterion 'sc-1' has blank or placeholder metric" in errors
    assert "Constraint 'c-1' has blank or placeholder description" in errors
    assert "Node 'scan' has a blank or placeholder description" in errors
    assert "Node 'scan' has a blank or placeholder system_prompt" in errors
    assert "Autonomous node 'summarize' has no tools or sub_agents" in errors
    assert "Autonomous node 'done' has no tools or sub_agents" not in errors


def test_validate_agent_package_accepts_absolute_path_and_skips_missing_tests(
    tmp_path,
    monkeypatch,
):
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = str(tmp_path)

    agent_dir = tmp_path / "examples" / "templates" / "demo_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "__init__.py").write_text(
        "from .agent import default_agent, edges, goal, nodes\n",
        encoding="utf-8",
    )
    (agent_dir / "agent.py").write_text(
        (
            "goal = object()\n"
            "nodes = []\n"
            "edges = []\n"
            "class _Agent:\n"
            "    def validate(self):\n"
            "        return True\n"
            "default_agent = _Agent()\n"
        ),
        encoding="utf-8",
    )
    (agent_dir / "mcp_servers.json").write_text("{}", encoding="utf-8")

    tool_calls: dict[str, str] = {}

    def _fake_validate_agent_tools(agent_path: str) -> dict:
        tool_calls["agent_path"] = agent_path
        return {"valid": True, "message": "PASS: tools ok"}

    framework_mod = types.ModuleType("framework")
    server_mod = types.ModuleType("framework.server")
    app_mod = types.ModuleType("framework.server.app")
    app_mod.validate_agent_path = lambda path: Path(path).resolve()
    server_mod.app = app_mod
    framework_mod.server = server_mod
    monkeypatch.setitem(sys.modules, "framework", framework_mod)
    monkeypatch.setitem(sys.modules, "framework.server", server_mod)
    monkeypatch.setitem(sys.modules, "framework.server.app", app_mod)

    class _Proc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _fake_run(cmd, **kwargs):
        command_text = " ".join(str(part) for part in cmd)
        if "missing = [a for a in ('goal', 'nodes', 'edges')" in command_text:
            return _Proc('{"valid": true}')
        if "from demo_agent import default_agent" in command_text:
            return _Proc("True")
        if "graph_ids = {n.id for n in agent.nodes}" in command_text:
            return _Proc('{"valid": true, "errors": []}')
        if "AgentRunner.load" in command_text:
            return _Proc("AgentRunner.load (graph-only): OK")
        raise AssertionError(f"Unexpected subprocess command: {cmd}")

    monkeypatch.setattr(mod, "_validate_agent_tools_impl", _fake_validate_agent_tools)
    monkeypatch.setattr(mod, "_behavior_validation_errors", lambda _module: [])
    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    report = mod._validate_agent_package_impl(str(agent_dir))

    assert report["valid"] is True
    assert report["agent_name"] == "demo_agent"
    assert report["agent_path"] == str(agent_dir)
    assert report["steps"]["tests"]["passed"] is True
    assert report["steps"]["tests"]["skipped"] is True
    assert str(agent_dir) in report["steps"]["tests"]["summary"]
    assert tool_calls["agent_path"] == str(agent_dir)


def test_behavior_validation_identity_prompt_placeholder_blocks_stage() -> None:
    mod = _load_coder_tools_server()

    blocking, warnings = mod._classify_behavior_validation_errors(
        ["identity_prompt still contains TODO placeholders"]
    )

    assert blocking == ["identity_prompt still contains TODO placeholders"]
    assert warnings == []


def test_behavior_validation_errors_accepts_complete_worker_nodes():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You summarize markdown files conservatively.",
        metadata=SimpleNamespace(
            description="Summarize long markdown files for manual review.",
            intro_message="Ready to review docs.",
        ),
        goal=SimpleNamespace(
            description="Summarize docs that exceed the word threshold.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Create concise draft summaries.",
                    metric="summaries_created",
                    target=">=1 when files exceed threshold",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Do not overwrite files.")],
        ),
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="scan",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                description="Scan docs and find long files.",
                system_prompt="Scan docs/ and compute word counts.",
                success_criteria="File inventory and over-limit files are set.",
            ),
            SimpleNamespace(
                id="review",
                client_facing=True,
                tools=[],
                sub_agents=[],
                description="Collect operator approval.",
                system_prompt="Ask the user whether to continue.",
                success_criteria="User provides a decision.",
            ),
            SimpleNamespace(
                id="done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                description="Finish and report.",
                system_prompt="Return final result.",
                success_criteria="Finished cleanly.",
            ),
        ],
    )

    assert mod._behavior_validation_errors(agent_module) == []


def test_behavior_validation_errors_allows_pure_llm_set_output_work_nodes():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You analyze resumes conservatively.",
        metadata=SimpleNamespace(
            description="Analyze resumes to identify strong target roles.",
            intro_message="Ready to analyze the resume.",
        ),
        goal=SimpleNamespace(
            description="Identify the strongest role targets from the resume.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Role analysis is stored for later steps.",
                    metric="role_analysis_ready",
                    target="1.0",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Stay faithful to the resume.")],
        ),
        entry_node="intake",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="intake",
                name="Intake",
                client_facing=False,
                node_type="event_loop",
                tools=[],
                sub_agents=[],
                input_keys=["resume_text"],
                output_keys=["resume_text", "role_analysis"],
                description="Analyze the resume and identify the strongest role fits.",
                system_prompt=(
                    "Analyze the user's resume, identify 3-5 strong role fits, "
                    "and call set_output for resume_text and role_analysis."
                ),
                success_criteria="Role analysis saved for downstream nodes.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                node_type="event_loop",
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert not any("Autonomous node 'intake'" in error for error in errors)


def test_behavior_validation_errors_allows_gcu_nodes_without_explicit_tools():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You coordinate browser work carefully.",
        metadata=SimpleNamespace(
            description="Use a browser worker to collect business URLs.",
            intro_message="Ready to collect business URLs.",
        ),
        goal=SimpleNamespace(
            description="Collect candidate businesses before enrichment.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Business list returned from browser worker.",
                    metric="business_list_ready",
                    target=">=5",
                )
            ],
            constraints=[
                SimpleNamespace(
                    id="c-1",
                    description="Use browser tools only inside the GCU.",
                )
            ],
        ),
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="map-search-worker",
                name="Maps Browser Worker",
                client_facing=False,
                node_type="gcu",
                tools=[],
                sub_agents=[],
                input_keys=["query"],
                output_keys=["business_list"],
                description="Browser worker that searches Google Maps.",
                system_prompt=(
                    "Search Google Maps for the query, collect relevant businesses, "
                    'and call set_output("business_list", ...).'
                ),
                success_criteria="Business list extracted.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                node_type="event_loop",
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert not any("Autonomous node 'map-search-worker'" in error for error in errors)


def test_validate_agent_tools_discovers_agent_local_tools_py(tmp_path, monkeypatch):
    _install_fake_framework(monkeypatch, tools_by_server={})
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = str(tmp_path)

    agent_dir = tmp_path / "examples" / "templates" / "local_tools_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "__init__.py").write_text("from .agent import nodes\n", encoding="utf-8")
    (agent_dir / "agent.py").write_text(
        (
            "from types import SimpleNamespace\n"
            "nodes = [SimpleNamespace(id='fetch', name='Fetch', tools=['bulk_fetch_emails'])]\n"
        ),
        encoding="utf-8",
    )
    (agent_dir / "mcp_servers.json").write_text("{}", encoding="utf-8")
    (agent_dir / "tools.py").write_text(
        (
            "from types import SimpleNamespace\n"
            "TOOLS = {'bulk_fetch_emails': SimpleNamespace(name='bulk_fetch_emails')}\n"
        ),
        encoding="utf-8",
    )

    framework_mod = sys.modules["framework"]
    server_mod = types.ModuleType("framework.server")
    app_mod = types.ModuleType("framework.server.app")
    app_mod.validate_agent_path = lambda path: Path(path).resolve()
    server_mod.app = app_mod
    framework_mod.server = server_mod
    monkeypatch.setitem(sys.modules, "framework.server", server_mod)
    monkeypatch.setitem(sys.modules, "framework.server.app", app_mod)

    result = mod._validate_agent_tools_impl(str(agent_dir))

    assert result["valid"] is True
    assert result["available_tool_count"] == 1
    assert "missing_tools" not in result


def test_validate_agent_tools_allows_local_only_agents_without_mcp_config(tmp_path, monkeypatch):
    _install_fake_framework(monkeypatch, tools_by_server={})
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = str(tmp_path)

    agent_dir = tmp_path / "exports" / "local_only_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "__init__.py").write_text("from .agent import nodes\n", encoding="utf-8")
    (agent_dir / "agent.py").write_text(
        (
            "from types import SimpleNamespace\n"
            "nodes = [SimpleNamespace(id='clock', name='Clock', tools=['get_current_timestamp'])]\n"
        ),
        encoding="utf-8",
    )
    (agent_dir / "tools.py").write_text(
        (
            "from types import SimpleNamespace\n"
            "TOOLS = {'get_current_timestamp': SimpleNamespace(name='get_current_timestamp')}\n"
        ),
        encoding="utf-8",
    )

    framework_mod = sys.modules["framework"]
    server_mod = types.ModuleType("framework.server")
    app_mod = types.ModuleType("framework.server.app")
    app_mod.validate_agent_path = lambda path: Path(path).resolve()
    server_mod.app = app_mod
    framework_mod.server = server_mod
    monkeypatch.setitem(sys.modules, "framework.server", server_mod)
    monkeypatch.setitem(sys.modules, "framework.server.app", app_mod)

    result = mod._validate_agent_tools_impl(str(agent_dir))

    assert result["valid"] is True
    assert result["available_tool_count"] == 1
    assert "error" not in result


def test_behavior_validation_errors_rejects_callable_style_tool_prompt_usage():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You are a careful file reviewer.",
        metadata=SimpleNamespace(
            description="Review markdown files.",
            intro_message="Ready to review markdown files.",
        ),
        goal=SimpleNamespace(
            description="Summarize large markdown files safely.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Scan markdown files.",
                    metric="scan_complete",
                    target="1.0",
                )
            ],
            constraints=[
                SimpleNamespace(
                    id="c-1",
                    description="Do not overwrite without approval.",
                )
            ],
        ),
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="scan",
                client_facing=False,
                tools=["list_dir", "load_data"],
                sub_agents=[],
                description="Scan the docs folder.",
                system_prompt=(
                    "Use list_dir(path='docs') first, then load_data(filename='x.md') "
                    "to inspect markdown files."
                ),
                success_criteria="Collect files to review.",
            ),
            SimpleNamespace(
                id="done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert (
        "Node 'scan' system_prompt uses callable-style tool syntax for 'list_dir'. "
        "Describe tool usage in prose instead of Python-style calls."
    ) in errors
    assert (
        "Node 'scan' system_prompt uses callable-style tool syntax for 'load_data'. "
        "Describe tool usage in prose instead of Python-style calls."
    ) in errors


def test_behavior_validation_errors_rejects_entry_intake_parsers_and_tool_aliases():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You process markdown review jobs.",
        metadata=SimpleNamespace(
            description="Condense markdown files for review.",
            intro_message="Ready to process markdown files.",
        ),
        goal=SimpleNamespace(
            description="Condense markdown files with review safeguards.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Collect runtime configuration once.",
                    metric="config_ready",
                    target="1.0",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Do not overwrite without review.")],
        ),
        entry_node="start-intake",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="start-intake",
                name="Intake Config",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["task"],
                output_keys=["docs_path", "review_path", "word_threshold", "style_rules"],
                description="Accept structured runtime task from Queen with docs path and rules.",
                system_prompt=(
                    "Parse the incoming task text into configuration values. "
                    "Use run_command if you need to inspect anything."
                ),
                success_criteria="All required config values parsed and validated.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert (
        "Entry node 'start-intake' appears to be an intake/config parser. "
        "The queen handles intake. Make the first real work node consume "
        "structured input_keys directly instead of reparsing a generic task string."
    ) in errors
    assert (
        "Node 'start-intake' system_prompt references unsupported tool alias "
        "'run_command'. Use the actual registered tool name 'execute_command_tool'."
    ) in errors


def test_behavior_validation_errors_rejects_structured_entry_intake_validators():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You sanitize markdown docs safely.",
        metadata=SimpleNamespace(
            description="Prepare cleaned markdown review copies.",
            intro_message="Ready to sanitize docs.",
        ),
        goal=SimpleNamespace(
            description="Sanitize markdown files with explicit approval before overwrite.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Runtime paths validated.",
                    metric="paths_ready",
                    target="1.0",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Never overwrite without review.")],
        ),
        entry_node="intake",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="intake",
                name="Intake & Validate Runtime Paths",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["docs_root", "review_root"],
                output_keys=["docs_root", "review_root", "run_id"],
                description="Read runtime task input and validate the filesystem paths.",
                system_prompt=(
                    "Accept structured runtime task input, validate runtime paths, "
                    "create review_root if missing, then pass the normalized values onward."
                ),
                success_criteria="Validated paths and emitted normalized runtime values.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert (
        "Entry node 'intake' appears to be an intake/config parser. "
        "The queen handles intake. Make the first real work node consume "
        "structured input_keys directly instead of reparsing a generic task string."
    ) in errors


def test_behavior_validation_errors_rejects_entry_intake_parser_with_scan_exclusions_text():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You generate local markdown reviews.",
        metadata=SimpleNamespace(
            description="Prepare review drafts for oversized markdown files.",
            intro_message="Ready to review markdown files.",
        ),
        goal=SimpleNamespace(
            description="Generate markdown review drafts from structured runtime inputs.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Runtime config normalized.",
                    metric="config_ready",
                    target="1.0",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Stay local-only.")],
        ),
        entry_node="intake-config",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="intake-config",
                name="Intake Config",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["target_dir", "word_threshold", "review_dir_mode"],
                output_keys=["target_dir", "word_threshold", "review_root", "scan_exclusions"],
                description=(
                    "Validate provided directory configuration and emit "
                    "normalized runtime settings."
                ),
                system_prompt=(
                    "Validate target_dir, normalize word_threshold, set scan_exclusions, "
                    "and resolve review_root before real work begins."
                ),
                success_criteria="Configuration normalized.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert (
        "Entry node 'intake-config' appears to be an intake/config parser. "
        "The queen handles intake. Make the first real work node consume "
        "structured input_keys directly instead of reparsing a generic task string."
    ) in errors


def test_behavior_validation_errors_rejects_output_dirs_that_must_preexist():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You review markdown rewrites safely.",
        metadata=SimpleNamespace(
            description="Prepare markdown review copies.",
            intro_message="Ready to review markdown files.",
        ),
        goal=SimpleNamespace(
            description="Write review copies for markdown documents.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Review copies are written for each eligible file.",
                    metric="review_copy_write_success_rate",
                    target=">=0.99",
                )
            ],
            constraints=[
                SimpleNamespace(
                    id="c-1",
                    description="Do not overwrite originals early.",
                )
            ],
        ),
        entry_node="start",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="start",
                name="Initialize Inputs",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["docs_dir", "review_dir", "word_threshold"],
                output_keys=["docs_dir", "review_dir", "word_threshold"],
                description="Validate directories before scanning markdown files.",
                system_prompt=(
                    "Validate docs_dir and review_dir exist and are directories before continuing."
                ),
                success_criteria="Paths validated.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert (
        "Entry node 'start' requires output path 'review_dir' to pre-exist. "
        "Output/review directories should be created if missing instead of "
        "blocking the run during intake validation."
    ) in errors


def test_behavior_validation_errors_allows_direct_scan_entry_nodes():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You sanitize markdown docs safely.",
        metadata=SimpleNamespace(
            description="Prepare cleaned markdown review copies.",
            intro_message="Ready to sanitize docs.",
        ),
        goal=SimpleNamespace(
            description="Sanitize markdown files with explicit approval before overwrite.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Markdown candidates discovered.",
                    metric="candidate_discovery_success_rate",
                    target=">=0.99",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Never overwrite without review.")],
        ),
        entry_node="scan-candidates",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="scan-candidates",
                name="Scan Markdown Candidates",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["source_dir", "review_dir"],
                output_keys=["source_dir", "review_dir", "candidates", "scan_stats", "rules"],
                description=(
                    "Consume structured source_dir/review_dir inputs directly, ensure review_dir "
                    "exists, recursively scan .md files, and detect candidate files."
                ),
                system_prompt=(
                    "Start markdown candidate discovery from structured inputs source_dir and "
                    "review_dir. Use execute_command_tool to create review_dir if missing, "
                    "recursively scan .md files, and emit candidates, scan_stats, and rules."
                ),
                success_criteria="Scanning completes and emits candidates, stats, and rules.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert not any("appears to be an intake/config parser" in error for error in errors)


def test_behavior_validation_errors_rejects_data_tools_used_for_review_root_workspace_paths():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You generate local markdown reviews.",
        metadata=SimpleNamespace(
            description="Generate review drafts and deliver a manifest.",
            intro_message="Ready to write local review outputs.",
        ),
        goal=SimpleNamespace(
            description="Write markdown review drafts and a manifest for the user.",
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Review outputs are saved.",
                    metric="review_outputs_written",
                    target=">=0.99",
                )
            ],
            constraints=[SimpleNamespace(id="c-1", description="Stay local-only.")],
        ),
        entry_node="scan",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="scan",
                name="Scan Markdown Files",
                client_facing=False,
                tools=["execute_command_tool"],
                sub_agents=[],
                input_keys=["target_dir"],
                output_keys=["review_root", "review_files"],
                description="Scan markdown files and prepare review targets.",
                system_prompt="Scan the target directory and emit review_root plus review_files.",
                success_criteria="Review targets prepared.",
            ),
            SimpleNamespace(
                id="write-manifest",
                name="Write Manifest",
                client_facing=False,
                tools=["save_data", "list_data_files", "serve_file_to_user"],
                sub_agents=[],
                input_keys=["review_root", "review_files"],
                output_keys=["manifest_file"],
                description="Write review artifacts for the user.",
                system_prompt=(
                    "Use save_data to persist each draft into review_root, then list files in "
                    "review_root with list_data_files and serve them to the user from review_root."
                ),
                success_criteria="Manifest and links delivered.",
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert any("uses session data tools" in error and "review_root" in error for error in errors)


def test_behavior_validation_errors_allows_session_data_tools_for_delivery_payloads():
    mod = _load_coder_tools_server()

    agent_module = SimpleNamespace(
        identity_prompt="You deliver markdown review artifacts safely.",
        metadata=SimpleNamespace(
            description="Deliver a session artifact for generated markdown reviews.",
            intro_message="Ready to deliver review artifacts.",
        ),
        goal=SimpleNamespace(
            description=(
                "Expose a manifest artifact and clickable link after local review generation."
            ),
            success_criteria=[
                SimpleNamespace(
                    id="sc-1",
                    description="Delivery payload is saved and link is returned.",
                    metric="artifact_delivery_success",
                    target=">=1 link",
                )
            ],
            constraints=[
                SimpleNamespace(
                    id="c-1",
                    description="Do not write workspace files here.",
                )
            ],
        ),
        entry_node="publish-links",
        terminal_nodes=["done"],
        nodes=[
            SimpleNamespace(
                id="publish-links",
                name="Publish Artifact Links",
                client_facing=False,
                tools=["save_data", "serve_file_to_user"],
                sub_agents=[],
                input_keys=[
                    "manifest_path",
                    "manifest_summary",
                    "scan_summary",
                    "draft_paths",
                    "review_dir",
                    "target_dir",
                    "word_threshold",
                ],
                output_keys=["artifact_links", "result"],
                description="Deliver session-scoped artifact links to the user.",
                system_prompt="""\
This is the session artifact delivery node.
Do NOT write workspace files here.

Allowed tools:
- save_data: store session-scoped delivery artifacts only.
- serve_file_to_user: return clickable links for saved session artifacts.

Tasks:
1) Create a compact delivery payload containing manifest_path, summary counts, and draft_paths.
2) Save that payload to session data via save_data (e.g., review_delivery.json).
3) Call serve_file_to_user for the saved session artifact and capture clickable URI(s).
4) Build final result object with:
   - status
   - target_dir
   - review_dir
   - word_threshold
   - total_markdown_files
   - flagged_files_count
   - draft_paths
   - manifest_path
   - artifact_links
""",
                success_criteria=(
                    "Clickable session artifact links are returned and final result is complete."
                ),
            ),
            SimpleNamespace(
                id="done",
                name="Done",
                client_facing=False,
                tools=[],
                sub_agents=[],
                input_keys=[],
                output_keys=[],
                description="Done.",
                system_prompt="Return completion message.",
                success_criteria="Done.",
            ),
        ],
    )

    errors = mod._behavior_validation_errors(agent_module)

    assert not any("uses session data tools" in error for error in errors)


def test_generated_agent_template_uses_isolated_manual_entry_point():
    mod = _load_coder_tools_server()
    source = Path(mod.__file__).read_text(encoding="utf-8")

    assert 'trigger_type="manual",' in source
    assert 'isolation_level="isolated"' in source


def test_generated_agent_template_avoids_intro_and_success_metric_todos():
    mod = _load_coder_tools_server()
    source = Path(mod.__file__).read_text(encoding="utf-8")

    assert "intro_message: str = {_default_intro_message(human_name, _draft_desc)!r}" in source
    assert 'metric="{_default_success_metric(i + 1)}"' in source
    assert 'target="{_default_success_target()}"' in source
    assert 'identity_prompt = "TODO: Add identity prompt."' not in source


def test_validation_reports_failed_tests_as_failed(monkeypatch) -> None:
    mod = _load_coder_tools_server()
    mod.PROJECT_ROOT = "/tmp/demo_project"

    monkeypatch.setattr(
        mod,
        "_resolve_agent_package_target",
        lambda _name: (Path("/tmp/demo_agent"), "demo_agent", "demo_agent"),
    )
    monkeypatch.setattr(
        mod,
        "_validate_agent_tools_impl",
        lambda _path: {"valid": True, "message": "ok"},
    )
    monkeypatch.setattr(mod, "_behavior_validation_errors", lambda _module: [])
    monkeypatch.setattr(
        mod,
        "_run_agent_tests_impl",
        lambda _path: {"failed": 1, "errors": 0, "summary": "1 failed", "failures": ["boom"]},
    )

    class _Proc:
        def __init__(self, stdout: str):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _fake_run(cmd, **kwargs):
        command_text = " ".join(str(part) for part in cmd)
        if "missing = [a for a in ('goal', 'nodes', 'edges')" in command_text:
            return _Proc('{"valid": true}')
        if "from demo_agent import default_agent" in command_text:
            return _Proc("True")
        if "graph_ids = {n.id for n in agent.nodes}" in command_text:
            return _Proc('{"valid": true, "errors": []}')
        if "AgentRunner.load" in command_text:
            return _Proc("AgentRunner.load (graph-only): OK")
        raise AssertionError(f"Unexpected subprocess command: {cmd}")

    monkeypatch.setitem(
        sys.modules,
        "demo_agent",
        types.SimpleNamespace(goal=object(), nodes=[], edges=[]),
    )
    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    report = mod._validate_agent_package_impl("demo_agent")

    assert report["valid"] is False
    assert report["steps"]["tests"]["passed"] is False
    assert report["steps"]["tests"]["failures"] == ["boom"]
