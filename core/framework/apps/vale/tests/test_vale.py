"""The vale on Hive: the One Above's powers, a villager's turn as a Hive agent, a whole day, and the HTTP API.

No model is called: villagers run real AgentLoops against a scripted streaming LLM, and
fate, the vale's gods and the host are their dice-rolling or plain stand-ins.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.apps.vale import overgod, physics, villager
from framework.apps.vale.engine import Powers
from framework.apps.vale.fate import StubFate
from framework.apps.vale.game import PHYSICS, Game, GameManager
from framework.apps.vale.god import StubGod
from framework.apps.vale.host import StubHost, normalize, part_record
from framework.apps.vale.novel import StubNovelist, chapters
from framework.apps.vale.outer import StubOuter
from framework.apps.vale.routes import register_routes
from framework.apps.vale.ullr import StubUllr
from framework.apps.vale.world import World, story_dir
from framework.llm.provider import LLMProvider, LLMResponse
from framework.llm.stream_events import FinishEvent, ToolCallEvent


class ScriptedVillagers(LLMProvider):
    """Every villager says one thing to everyone, then reports. Alternate stream calls: say, report."""

    model = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, system="", tools=None, max_tokens=4096, **kw):
        self.calls += 1
        names = {t.name for t in tools or []}
        said = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)
        if "say" in names and not said:
            yield ToolCallEvent(
                tool_use_id=f"c{self.calls}", tool_name="say", tool_input={"to": "everyone", "text": "Has anyone else seen the red water?"}
            )
        else:
            yield ToolCallEvent(
                tool_use_id=f"c{self.calls}",
                tool_name="report_to_parent",
                tool_input={
                    "status": "success",
                    "summary": "spoke",
                    "data": {"memory": "I asked about the red water.", "mood": "uneasy", "thought": "Somebody must know."},
                },
            )
        yield FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="scripted")

    def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="{}", model="scripted", stop_reason="stop")


def stub_game(gid: str, path: Path) -> Game:
    return Game(
        gid,
        path,
        powers=Powers(fate=StubFate(), god=StubGod(1), outer=StubOuter(1), ullr=StubUllr(1)),
        villager_llm=ScriptedVillagers(),
        host=StubHost(),
        novelist=StubNovelist(),
    )


@pytest.fixture
def world(tmp_path: Path):
    World.create(tmp_path / "w", seed=3, overrides=PHYSICS).close()
    w = World(tmp_path / "w")
    w.day = 1
    w.today = {"activations": 0, "tired": 0, "rumors": 0, "llm_errors": 0, "checks": 0}
    yield w
    w.close()


# ---------------------------------------------------------------------------- the One Above


def test_whisper_costs_awe_and_teaches_the_voice(world: World) -> None:
    record = overgod.act(world, "whisper", {"to": "Wynn", "text": "Sing among the stones."})
    o = overgod.state(world)
    assert record["cost"] == 1 and o["awe"] == overgod.START_AWE - 1
    assert o["known_by"] == ["wynn"]
    dream = [s for s in world.signals.values() if s.kind == "dream" and s.source == "overgod"]
    assert dream and dream[0].audience == ["wynn"]
    # Having heard the voice, Wynn can pray to it; nobody else can.
    assert any(
        "the One Above" in (t.parameters["properties"]["to"]["description"])
        for t in villager.tools_for(world, world.agents["wynn"])
        if t.name == "pray"
    )
    assert not any(
        "the One Above" in (t.parameters["properties"]["to"]["description"])
        for t in villager.tools_for(world, world.agents["bram"])
        if t.name == "pray"
    )


def test_locked_and_unaffordable_powers_are_refused(world: World) -> None:
    with pytest.raises(overgod.OvergodError, match="unlocks with the tier of Wrath"):
        overgod.act(world, "flood")
    overgod.state(world)["tier"] = 4
    with pytest.raises(overgod.OvergodError, match="costs 10 Awe"):
        overgod.act(world, "raise_stone")
    with pytest.raises(overgod.OvergodError, match="no villager called"):
        overgod.act(world, "whisper", {"to": "Nobody", "text": "x"})


def test_a_prayer_to_the_voice_closes_the_first_chapter(world: World) -> None:
    overgod.act(world, "whisper", {"to": "Wynn", "text": "I am above them all."})
    from framework.apps.vale import act

    act.pray(world, world.agents["wynn"], {"to": "the One Above", "text": "Who are you?"}, "a1")
    done = overgod.advance_chapters(world)
    assert [c["chapter"] for c in done] == ["voice"]
    assert overgod.state(world)["tier"] == 2


def test_disasters_change_the_hidden_world(world: World) -> None:
    overgod.state(world).update(tier=3, awe=12)
    before = world.hidden["blight"]["fenford"]
    overgod.act(world, "flood")
    assert world.hidden["blight"]["fenford"] > before
    overgod.act(world, "plague", {"at": "ashmere"})
    assert world.hidden["sickness"]["ashmere"] >= 0.35


def test_a_decree_reaches_the_gods_prompt(world: World) -> None:
    overgod.state(world).update(tier=4, awe=12)
    overgod.act(world, "decree", {"god": "god", "text": "Speak of the song.", "days": 2})
    assert "Speak of the song." in overgod.decree_for(world, "god")
    world.day += 3
    assert overgod.decree_for(world, "god") == ""


# ---------------------------------------------------------------------------- a villager is a Hive agent


@pytest.mark.asyncio
async def test_a_villager_turn_runs_as_a_hive_agent(world: World) -> None:
    firing = physics.Firing("bram", 3.0, 0.5, [], None, ["water"])
    record = await villager.run_turn(world, firing, ScriptedVillagers())
    assert record["error"] is None
    assert record["done"] == ['said to everyone: "Has anyone else seen the red water?"']
    assert world.read_memory("bram") == "I asked about the red water."
    assert world.agents["bram"].mood == "uneasy"
    assert any(s.kind == "speech" and s.source == "bram" for s in world.signals.values())


# ---------------------------------------------------------------------------- a whole day


@pytest.mark.asyncio
async def test_a_day_runs_part_by_part(tmp_path: Path) -> None:
    manager = GameManager(tmp_path / "games", game_factory=stub_game)
    game = manager.create("Test vale", seed=5)
    for _ in range(6):
        await game.step()
    snap = game.snapshot()
    assert snap["clock"] == {"day": 2, "wave": 0}
    kinds = {i["type"] for i in game.feed()}
    assert {"stir", "night", "awe"} <= kinds
    assert snap["overgod"]["awe"] > overgod.START_AWE  # the dawn gave Awe back
    await manager.close()


# ---------------------------------------------------------------------------- the HTTP API


@pytest.mark.asyncio
async def test_the_api_creates_acts_and_advances(tmp_path: Path) -> None:
    app = web.Application()
    register_routes(app, GameManager(tmp_path / "games", game_factory=stub_game))
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/vale/games", json={"name": "API vale", "seed": 2})
        assert resp.status == 201
        gid = (await resp.json())["id"]
        resp = await client.post(f"/api/vale/games/{gid}/act", json={"power": "whisper", "args": {"to": "kell", "text": "Wolves."}})
        assert resp.status == 200
        resp = await client.post(f"/api/vale/games/{gid}/act", json={"power": "flood"})
        assert resp.status == 400 and "Wrath" in (await resp.json())["error"]
        resp = await client.post(f"/api/vale/games/{gid}/advance", json={"waves": 2})
        assert resp.status == 202
        for _ in range(100):
            snap = await (await client.get(f"/api/vale/games/{gid}")).json()
            if snap["status"] == "idle":
                break
            await asyncio.sleep(0.05)
        assert snap["clock"] == {"day": 1, "wave": 2}
        items = (await (await client.get(f"/api/vale/games/{gid}/feed")).json())["items"]
        assert any(i["type"] == "dream" and i["by"] == "overgod" for i in items)
        assert (await client.get(f"/api/vale/games/{gid}/villagers/wynn")).status == 200
        assert (await client.get("/api/vale/games/nope")).status == 404


# ---------------------------------------------------------------------------- the vale in Chinese


@pytest.fixture
def zh_world(tmp_path: Path):
    World.create(tmp_path / "zh", template=story_dir("ashmere", "zh"), seed=3, overrides=PHYSICS).close()
    w = World(tmp_path / "zh")
    w.day = 1
    w.today = {"activations": 0, "tired": 0, "rumors": 0, "llm_errors": 0, "checks": 0}
    yield w
    w.close()


@pytest.mark.parametrize(
    ("said", "good"),
    [
        ("一罐清水", "water"),
        ("药草", "herbs"),
        ("药水", "remedy"),
        ("墨水", "ink"),
        ("溺灯的麦酒", "ale"),
        ("两个带盖的罐子", "jars"),
        ("rope", "rope"),
    ],
)
def test_chinese_goods_are_the_story_goods(zh_world: World, said: str, good: str) -> None:
    from framework.apps.vale import act

    assert act.goods(zh_world, said) == good


def test_chinese_names_places_and_topics_resolve(zh_world: World) -> None:
    assert zh_world.resolve_person("老布拉姆").id == "bram"
    assert zh_world.resolve_person("嬷嬷").id == "isolde"
    assert zh_world.resolve_place("古冢") == "barrow_hill"
    assert zh_world.resolve_place("村里") == "ashmere"
    assert zh_world.tags("井水里有股铁锈味，孩子咳出了血。") == ["water", "rust", "sickness", "children"]


def test_a_chinese_prayer_reaches_the_one_above(zh_world: World) -> None:
    from framework.apps.vale import act

    overgod.act(zh_world, "whisper", {"to": "温", "text": "黄昏时，在七石之间歌唱。"})
    act.pray(zh_world, zh_world.agents["wynn"], {"to": "至上者", "text": "你是谁？"}, "a1")
    assert zh_world.hidden["prayers"][-1]["to"] == "overgod"
    assert [c["title"] for c in overgod.advance_chapters(zh_world)] == ["至上之声"]


def test_a_chinese_villager_sees_chinese(zh_world: World) -> None:
    from framework.apps.vale import mind

    moment = mind.moment(zh_world, zh_world.agents["wynn"], physics.Firing("wynn", 3.0, 0.5, [], None, []))
    assert moment.startswith("第1天") and "牧人羊圈" in moment
    pray = next(t for t in villager.tools_for(zh_world, zh_world.agents["bagel"]) if t.name == "pray")
    assert "主人" in pray.parameters["properties"]["to"]["description"]


@pytest.mark.asyncio
async def test_a_chinese_day_runs(tmp_path: Path) -> None:
    manager = GameManager(tmp_path / "games", game_factory=stub_game)
    game = manager.create(seed=5, lang="zh")
    for _ in range(6):
        await game.step()
    snap = game.snapshot()
    assert snap["lang"] == "zh" and snap["story"]["title"] == "灰湖谷" and snap["waves"][0] == "黎明"
    assert snap["clock"] == {"day": 2, "wave": 0}
    await manager.close()


@pytest.mark.asyncio
async def test_the_api_lists_stories_and_refuses_a_missing_language(tmp_path: Path) -> None:
    app = web.Application()
    register_routes(app, GameManager(tmp_path / "games", game_factory=stub_game))
    async with TestClient(TestServer(app)) as client:
        stories = (await (await client.get("/api/vale/stories")).json())["stories"]
        assert {s["id"]: sorted(s["langs"]) for s in stories} == {"ashmere": ["en", "zh"]}
        resp = await client.post("/api/vale/games", json={"lang": "zh", "seed": 1})
        assert resp.status == 201 and (await resp.json())["lang"] == "zh"
        resp = await client.post("/api/vale/games", json={"lang": "../en"})
        assert resp.status == 400


# ---------------------------------------------------------------------------- the dice are never skipped


def test_every_attempt_is_rolled_even_when_fate_asks_to_skip(world: World) -> None:
    from framework.apps.vale import dice, fate

    plan = {"roll": False, "skill": "healing", "roller": "elspeth", "outcomes": {b: {"public": b, "effects": []} for b in dice.BANDS}}
    result = fate.settle(world, plan, ["elspeth"])
    assert result["check"] is not None
    assert result["outcome"] == result["check"]["band"] == result["public"]


# ---------------------------------------------------------------------------- the host


def _attempt(ref_agent: str = "bram") -> dict:
    check = {"skill": "craft", "roller": ref_agent, "base": 70, "mods": [], "target": 70, "fumble": 96, "roll": 12, "band": "critical"}
    return {
        "type": "attempt",
        "agent": ref_agent,
        "place": "fold",
        "what": "mend the gate",
        "outcome": "critical",
        "public": "The gate holds.",
        "check": check,
    }


def test_the_host_never_drops_a_roll(world: World) -> None:
    record, rolls = part_record(world, [_attempt()])
    assert list(rolls) == ["R1"] and "[R1]" in record
    script = normalize(world, {"beats": [{"kind": "roll", "ref": "R9", "before": "x"}, {"kind": "scene", "text": "Wind on the fold."}]}, rolls)
    kinds = [b["kind"] for b in script["beats"]]
    assert kinds == ["open", "scene", "roll", "turn"]
    assert script["beats"][2]["roll"]["check"]["roll"] == 12


@pytest.mark.asyncio
async def test_every_part_ends_with_the_hosts_script(tmp_path: Path) -> None:
    manager = GameManager(tmp_path / "games", game_factory=stub_game)
    game = manager.create("Hosted", seed=5)
    await game.step()
    await game.step()
    hosts = [i for i in game.feed() if i["type"] == "host"]
    assert [(h["day"], h["wave"]) for h in hosts] == [(1, 0), (1, 1)]
    assert all(h["beats"][0]["kind"] == "open" and h["beats"][-1]["kind"] == "turn" for h in hosts)
    rolled = [i for i in game.feed() if i["type"] in ("attempt", "undertaking") and i.get("check")]
    shown = [b for h in hosts for b in h["beats"] if b["kind"] == "roll"]
    assert len(shown) == len(rolled)
    await manager.close()


def test_the_host_reads_a_chinese_part_in_chinese(zh_world: World) -> None:
    item = {**_attempt(), "what": "修好羊圈的门", "public": "门牢牢地立住了。"}
    record, _ = part_record(zh_world, [item])
    assert "老布拉姆 [bram] 在牧人羊圈 [fold] 尝试：“修好羊圈的门”" in record and "大成功" in record


# ---------------------------------------------------------------------------- the novel


@pytest.mark.asyncio
async def test_a_finished_day_becomes_a_chapter(tmp_path: Path) -> None:
    manager = GameManager(tmp_path / "games", game_factory=stub_game)
    game = manager.create("Novel", seed=5)
    for _ in range(6):
        await game.step()
    await asyncio.gather(*game._chapters)
    book = chapters(game.dir)
    assert [c["day"] for c in book] == [1]
    assert book[0]["text"].startswith("# Chapter 1: Day 1")
    assert "Has anyone else seen the red water?" in book[0]["text"]
    await manager.close()


@pytest.mark.asyncio
async def test_the_api_reads_the_novel_and_refuses_an_unfinished_day(tmp_path: Path) -> None:
    app = web.Application()
    register_routes(app, GameManager(tmp_path / "games", game_factory=stub_game))
    async with TestClient(TestServer(app)) as client:
        gid = (await (await client.post("/api/vale/games", json={"seed": 2})).json())["id"]
        assert (await (await client.get(f"/api/vale/games/{gid}/novel")).json()) == {"chapters": [], "writing": []}
        resp = await client.post(f"/api/vale/games/{gid}/novel/1")
        assert resp.status == 409 and "not over" in (await resp.json())["error"]
