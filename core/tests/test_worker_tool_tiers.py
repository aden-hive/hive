"""Worker-side tool tiering (framework.tools.tool_tiers).

Covers the ToolTierState engine, the shared search_tools factory, the
searchable-tools reminder for worker streams, the dynamic-refresh synthetic
preservation, and the dispatch-guard contract pieces that don't need a full
loop run.
"""

import json
from types import SimpleNamespace

import pytest

from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.reminders import ReminderContext, ReminderPoint
from framework.agent_loop.tool_skill_reminders import SearchableToolsReminderSource
from framework.llm.provider import Tool
from framework.tools.tool_tiers import ToolTierState, build_search_tools


def _tool(name: str, desc: str = "") -> Tool:
    return Tool(name=name, description=desc or f"desc of {name}", parameters={"type": "object"})


def _tier(**kw) -> ToolTierState:
    defaults = {
        "pool": [_tool("browser_interact"), _tool("browser_upload"), _tool("send_email"), _tool("task_update")],
        "always_enabled_names": {"browser_interact"},
        "gateable_names": {"browser_interact", "browser_upload", "send_email"},
    }
    defaults.update(kw)
    t = ToolTierState(**defaults)
    t.rebuild()
    return t


class TestToolTierState:
    def test_split_partitions_pool(self):
        t = _tier()
        eager = {x.name for x in t.get_current_tools()}
        searchable = {x.name for x in t.get_searchable_tools()}
        # always-enabled + non-gateable are eager; the rest searchable.
        assert eager == {"browser_interact", "task_update"}
        assert searchable == {"browser_upload", "send_email"}
        assert t.searchable_names() == searchable

    def test_empty_keep_set_disables_split(self):
        t = _tier(always_enabled_names=set())
        assert {x.name for x in t.get_current_tools()} == {
            "browser_interact",
            "browser_upload",
            "send_email",
            "task_update",
        }
        assert t.get_searchable_tools() == []

    def test_eager_list_is_memoized_object(self):
        t = _tier()
        assert t.get_current_tools() is t.get_current_tools()

    def test_promote_moves_to_eager_and_persists(self, tmp_path):
        t = _tier(persist_path=tmp_path / "tool_tiers.json")
        newly = t.promote_searched_tools(["send_email", "send_email"])
        assert newly == ["send_email"]
        assert "send_email" in {x.name for x in t.get_current_tools()}
        assert "send_email" not in t.searchable_names()
        assert json.loads((tmp_path / "tool_tiers.json").read_text())["loaded_tools"] == ["send_email"]
        # Second promote of the same name is a no-op.
        assert t.promote_searched_tools(["send_email"]) == []

    def test_restore_drops_unknown_and_disallowed(self, tmp_path):
        t = _tier(enabled_allowlist=["browser_upload"])
        t.restore_loaded_tools(["browser_upload", "gone_tool", "send_email"], {"browser_upload", "send_email"})
        # send_email fails the allowlist; gone_tool is unregistered.
        assert t.loaded_tool_names == ["browser_upload"]

    def test_persist_roundtrip(self, tmp_path):
        path = tmp_path / "tool_tiers.json"
        t = _tier(persist_path=path)
        t.promote_searched_tools(["browser_upload"])
        t2 = _tier(persist_path=path)
        t2.restore_loaded_tools(t2.load_persisted_tools(), {x.name for x in t2.pool})
        t2.rebuild()
        assert "browser_upload" in {x.name for x in t2.get_current_tools()}

    def test_allowlist_gates_membership(self):
        t = _tier(enabled_allowlist=["send_email"])
        allowed = {x.name for x in t._filtered_pool}
        # browser_upload is gateable and not allowlisted -> excluded entirely.
        assert "browser_upload" not in allowed
        assert {"browser_interact", "send_email", "task_update"} <= allowed


class TestSearchToolsFactory:
    @pytest.mark.asyncio
    async def test_select_promotes_and_reports(self):
        t = _tier()
        _tool_schema, handler = build_search_tools(t)
        payload = json.loads(await handler(query="select:send_email"))
        assert payload["loaded"] == ["send_email"]
        assert "send_email" in {x.name for x in t.get_current_tools()}

    @pytest.mark.asyncio
    async def test_keyword_match(self):
        t = _tier(
            pool=[_tool("send_email", "Send an email via the configured sender"), _tool("browser_interact")],
            always_enabled_names={"browser_interact"},
            gateable_names={"send_email", "browser_interact"},
        )
        _s, handler = build_search_tools(t)
        payload = json.loads(await handler(query="send email"))
        assert payload["loaded"] == ["send_email"]

    @pytest.mark.asyncio
    async def test_already_loaded_is_reported(self):
        t = _tier()
        _s, handler = build_search_tools(t)
        payload = json.loads(await handler(query="select:browser_interact"))
        assert payload["loaded"] == []
        assert "browser_interact" in payload.get("already_loaded", [])

    def test_schema_matches_queen_registration(self):
        # The Tool description is the queen-visible schema; keep it stable so
        # queen prompts don't churn (byte-identical contract with the
        # original registration in queen_lifecycle_tools).
        t = _tier()
        schema, _h = build_search_tools(t)
        assert schema.name == "search_tools"
        assert "select:name_a,name_b" in schema.description
        assert set(schema.parameters["properties"].keys()) == {"query", "max_results"}


class TestWorkerReminder:
    def _ctx(self, **attrs):
        return SimpleNamespace(**attrs)

    def test_applies_to_worker_with_provider(self):
        src = SearchableToolsReminderSource()
        worker = self._ctx(is_queen_stream=False, searchable_tools_provider=lambda: [])
        assert src.applies_to(worker) is True

    def test_skips_worker_without_provider(self):
        src = SearchableToolsReminderSource()
        worker = self._ctx(is_queen_stream=False)
        assert src.applies_to(worker) is False

    def test_still_applies_to_queen(self):
        src = SearchableToolsReminderSource()
        assert src.applies_to(self._ctx(is_queen_stream=True)) is True

    @pytest.mark.asyncio
    async def test_renders_worker_manifest(self):
        src = SearchableToolsReminderSource()
        t = _tier()
        ctx = self._ctx(
            is_queen_stream=False,
            searchable_tools_provider=t.get_searchable_tools,
            loaded_tool_names_provider=lambda: list(t.loaded_tool_names),
        )
        body = await src.render(ReminderContext(point=ReminderPoint.SESSION_START, agent_ctx=ctx))
        assert body is not None
        assert "browser_upload" in body and "send_email" in body

    @pytest.mark.asyncio
    async def test_loaded_tool_departs_silently(self):
        src = SearchableToolsReminderSource()
        t = _tier()
        ctx = self._ctx(
            is_queen_stream=False,
            searchable_tools_provider=t.get_searchable_tools,
            loaded_tool_names_provider=lambda: list(t.loaded_tool_names),
        )
        await src.render(ReminderContext(point=ReminderPoint.SESSION_START, agent_ctx=ctx))
        t.promote_searched_tools(["send_email"])
        body = await src.render(ReminderContext(point=ReminderPoint.POST_TOOL_USE, agent_ctx=ctx))
        # send_email left the searchable set because it was loaded -> silent.
        assert body is None


class TestDynamicRefreshSynthetics:
    def test_worker_synthetics_survive_refresh(self):
        t = _tier()
        report = _tool("report_to_parent")
        search = _tool("search_tools")
        ask = _tool("ask_user")
        tools = list(t.get_current_tools()) + [report, search, ask]
        ctx = SimpleNamespace(dynamic_tools_provider=t.get_current_tools)
        AgentLoop._refresh_dynamic_tools(SimpleNamespace(_DYNAMIC_REFRESH_SYNTHETIC_NAMES=AgentLoop._DYNAMIC_REFRESH_SYNTHETIC_NAMES), ctx, tools)
        names = [x.name for x in tools]
        assert "report_to_parent" in names
        assert "search_tools" in names
        assert "ask_user" in names
        # No duplicates even though search_tools is both synthetic-preserved
        # and potentially provider-supplied.
        assert len(names) == len(set(names))

    def test_provider_supplied_search_tools_not_duplicated(self):
        # Queen path: provider output already contains search_tools.
        t = _tier(pool=[_tool("search_tools"), _tool("browser_interact")], always_enabled_names=set(), gateable_names=set())
        tools = list(t.get_current_tools())
        ctx = SimpleNamespace(dynamic_tools_provider=t.get_current_tools)
        AgentLoop._refresh_dynamic_tools(SimpleNamespace(_DYNAMIC_REFRESH_SYNTHETIC_NAMES=AgentLoop._DYNAMIC_REFRESH_SYNTHETIC_NAMES), ctx, tools)
        assert [x.name for x in tools].count("search_tools") == 1


class TestPromptGatingUsesTier:
    def test_gating_reads_eager_set_not_pool(self):
        from framework.agent_loop.prompting import build_prompt_spec

        t = _tier(
            pool=[_tool("browser_interact"), _tool("terminal_exec")],
            always_enabled_names={"terminal_exec"},
            gateable_names={"browser_interact", "terminal_exec"},
        )
        ctx = SimpleNamespace(
            available_tools=list(t.pool),
            tool_tier_state=t,
            memory_prompt="",
            dynamic_memory_provider=None,
            skills_catalog_prompt="CATALOG",
            dynamic_skills_catalog_provider=None,
            colony_binding_provider=None,
            identity_prompt="",
            narrative="",
            accounts_prompt="",
            protocols_prompt="",
            agent_spec=SimpleNamespace(system_prompt="focus", agent_type="event_loop", output_keys=(), report_schema=None),
        )
        spec = build_prompt_spec(ctx)
        # browser_interact is deferred -> the browser foundation guide must
        # NOT be pre-activated into the catalog.
        assert "Pre-Activated Skill: hive.browser-automation" not in spec.skills_catalog_prompt
        # Promote it -> the guide appears on the next prompt build.
        t.promote_searched_tools(["browser_interact"])
        spec2 = build_prompt_spec(ctx)
        assert "Pre-Activated Skill: hive.browser-automation" in spec2.skills_catalog_prompt
