"""Tests for the queen's mid-run write_skill tool.

Companion to ``create_colony``'s inline-skill writing. Covers:
  - Happy path: writes ``~/.hive/colonies/{name}/skills/{skill_name}/`` and
    returns the path so the queen can immediately reference it.
  - Replace-existing: re-writing the same name replaces in place.
  - No colony bound: fails cleanly (the tool is meaningless outside a colony).
  - Invalid input: surfaces validator errors.
  - Source-path mode: copies an on-disk skill folder into the colony scope,
    optionally renaming, and rejects ambiguous mixed-mode payloads.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.host.event_bus import EventBus
from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools


def _session_for_colony(colony_id: str | None) -> SimpleNamespace:
    """Build a minimal session-like object the tool reads from."""
    bus = EventBus()
    return SimpleNamespace(
        id=f"session_for_{colony_id or 'none'}",
        colony_id=colony_id,
        colony=None,
        colony_runtime=None,
        event_bus=bus,
        worker_path=None,
        available_triggers={},
        active_trigger_ids=set(),
    )


def _registry_for(session: SimpleNamespace) -> ToolRegistry:
    reg = ToolRegistry()
    register_queen_lifecycle_tools(reg, session=session, session_id=session.id)
    return reg


async def _call_write_skill(reg: ToolRegistry, payload: dict) -> dict:
    executor = reg.get_executor()
    result = executor(ToolUse(id="tu_write_skill", name="write_skill", input=payload))
    if asyncio.iscoroutine(result):
        result = await result
    return json.loads(result.content)


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_skill_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony("research_competitors")
    reg = _registry_for(session)

    payload = {
        "skill_name": "competitor-research-protocol",
        "skill_description": "Per-row competitor research procedure for the Series A memo.",
        "skill_body": (
            "# Competitor Research Protocol\n\n"
            "For each row, fill: website, year_founded, total_funding_usd, "
            "primary_segment, pricing_model. Use tracker_upsert with "
            "company_name as the key.\n"
        ),
    }
    body = await _call_write_skill(reg, payload)

    assert body.get("success") is True, body
    assert body["skill_name"] == "competitor-research-protocol"
    assert body["replaced"] is False

    skill_dir = tmp_path / "research_competitors" / "skills" / "competitor-research-protocol"
    assert skill_dir.is_dir()
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.is_file()
    text = skill_md.read_text(encoding="utf-8")
    assert "Competitor Research Protocol" in text
    assert "tracker_upsert" in text


@pytest.mark.asyncio
async def test_write_skill_replaces_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    p1 = await _call_write_skill(
        reg,
        {
            "skill_name": "protocol-v1",
            "skill_description": "first draft",
            "skill_body": "# v1\nfirst content",
        },
    )
    assert p1["success"] is True
    assert p1["replaced"] is False

    p2 = await _call_write_skill(
        reg,
        {
            "skill_name": "protocol-v1",
            "skill_description": "revised",
            "skill_body": "# v1\nNEW content",
        },
    )
    assert p2["success"] is True
    assert p2["replaced"] is True

    skill_md = tmp_path / "c1" / "skills" / "protocol-v1" / "SKILL.md"
    assert "NEW content" in skill_md.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_write_skill_no_colony_returns_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When the session is NOT bound to a colony (queen DM only), refuse cleanly."""
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony(colony_id=None)
    reg = _registry_for(session)

    body = await _call_write_skill(
        reg,
        {
            "skill_name": "x",
            "skill_description": "y",
            "skill_body": "z",
        },
    )
    assert "error" in body
    assert "no colony" in body["error"].lower()


@pytest.mark.asyncio
async def test_write_skill_validation_error_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty body / bad name → validator error returned to the queen."""
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(
        reg,
        {
            "skill_name": "BadName",  # uppercase rejected
            "skill_description": "ok",
            "skill_body": "ok",
        },
    )
    assert "error" in body
    # Helpful hint included.
    assert "hint" in body


# ---------------------------------------------------------------------------
# source_path (copy-from-disk) mode
# ---------------------------------------------------------------------------


def _materialize_source_skill(
    root: Path,
    *,
    name: str = "source-skill",
    description: str = "Source skill copied into the colony.",
    body: str = "# Source Skill\n\nDo the thing.\n",
    aux_files: dict[str, str] | None = None,
) -> Path:
    """Write a fake on-disk skill folder for tests to point source_path at."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    for rel, content in (aux_files or {}).items():
        target = skill_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return skill_dir


@pytest.mark.asyncio
async def test_write_skill_copies_from_source_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """source_path mode pulls SKILL.md + aux files into the colony scope."""
    colonies_root = tmp_path / "colonies"
    sources_root = tmp_path / "sources"
    colonies_root.mkdir()
    sources_root.mkdir()
    monkeypatch.setattr("framework.config.COLONIES_DIR", colonies_root)

    src = _materialize_source_skill(
        sources_root,
        name="probe-protocol",
        description="Probe one row to validate the protocol.",
        body="# Probe Protocol\n\nRun tracker_query then tracker_upsert.\n",
        aux_files={
            "scripts/helper.py": "print('hi')\n",
            "refs/notes.md": "see go/probe-protocol\n",
        },
    )

    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(src)})

    assert body.get("success") is True, body
    assert body["skill_name"] == "probe-protocol"
    assert body["files_copied"] == 2

    dest = colonies_root / "c1" / "skills" / "probe-protocol"
    assert (dest / "SKILL.md").read_text(encoding="utf-8").count("Probe Protocol") == 1
    assert (dest / "scripts" / "helper.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (dest / "refs" / "notes.md").read_text(encoding="utf-8").startswith("see go/")


@pytest.mark.asyncio
async def test_write_skill_source_path_accepts_skill_md_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing the SKILL.md path (not the dir) is normalized to the parent."""
    colonies_root = tmp_path / "colonies"
    sources_root = tmp_path / "sources"
    colonies_root.mkdir()
    sources_root.mkdir()
    monkeypatch.setattr("framework.config.COLONIES_DIR", colonies_root)

    src = _materialize_source_skill(sources_root, name="direct-md")
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(src / "SKILL.md")})
    assert body.get("success") is True, body
    assert body["skill_name"] == "direct-md"


@pytest.mark.asyncio
async def test_write_skill_source_path_renames_via_skill_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """skill_name overrides the source's frontmatter name when copying."""
    colonies_root = tmp_path / "colonies"
    sources_root = tmp_path / "sources"
    colonies_root.mkdir()
    sources_root.mkdir()
    monkeypatch.setattr("framework.config.COLONIES_DIR", colonies_root)

    src = _materialize_source_skill(sources_root, name="orig-name")
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(src), "skill_name": "renamed-on-copy"})
    assert body.get("success") is True, body
    assert body["skill_name"] == "renamed-on-copy"
    assert (colonies_root / "c1" / "skills" / "renamed-on-copy" / "SKILL.md").is_file()
    assert not (colonies_root / "c1" / "skills" / "orig-name").exists()


@pytest.mark.asyncio
async def test_write_skill_source_path_rejects_inline_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mixing source_path with skill_body/description/files is an error."""
    colonies_root = tmp_path / "colonies"
    sources_root = tmp_path / "sources"
    colonies_root.mkdir()
    sources_root.mkdir()
    monkeypatch.setattr("framework.config.COLONIES_DIR", colonies_root)

    src = _materialize_source_skill(sources_root, name="mixed-mode")
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(
        reg,
        {
            "source_path": str(src),
            "skill_body": "# Inline override\n",
        },
    )
    assert "error" in body
    assert "source_path mode" in body["error"]


@pytest.mark.asyncio
async def test_write_skill_source_path_missing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(tmp_path / "no-such-skill")})
    assert "error" in body
    assert "does not exist" in body["error"]


@pytest.mark.asyncio
async def test_write_skill_source_path_dir_without_skill_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    empty = tmp_path / "empty-skill"
    empty.mkdir()
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(empty)})
    assert "error" in body
    assert "SKILL.md" in body["error"]


@pytest.mark.asyncio
async def test_write_skill_source_path_rejects_binary_aux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Binary aux files trip a clear error rather than silently dropping."""
    colonies_root = tmp_path / "colonies"
    sources_root = tmp_path / "sources"
    colonies_root.mkdir()
    sources_root.mkdir()
    monkeypatch.setattr("framework.config.COLONIES_DIR", colonies_root)

    src = _materialize_source_skill(sources_root, name="has-binary")
    (src / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\xfd")

    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"source_path": str(src)})
    assert "error" in body
    assert "image.bin" in body["error"]


@pytest.mark.asyncio
async def test_write_skill_inline_mode_requires_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without source_path, omitting required inline params is an error."""
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    session = _session_for_colony("c1")
    reg = _registry_for(session)

    body = await _call_write_skill(reg, {"skill_name": "only-name"})
    assert "error" in body
    assert "inline mode requires" in body["error"]
