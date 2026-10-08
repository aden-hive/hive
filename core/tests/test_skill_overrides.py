"""Tests for the per-scope skill override store and its interaction with SkillsManager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from framework.skills.config import SkillsConfig
from framework.skills.discovery import ExtraScope
from framework.skills.manager import SkillsManager, SkillsManagerConfig
from framework.skills.overrides import (
    OverrideEntry,
    Provenance,
    SkillOverrideStore,
)
from framework.skills.skill_writer import build_draft, write_skill


def _write_skill_file(base: Path, name: str, description: str = "desc") -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nbody\n",
        encoding="utf-8",
    )
    return skill_dir


class TestSkillOverrideStore:
    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        store = SkillOverrideStore.load(tmp_path / "skills_overrides.json", scope_label="queen:x")
        assert store.overrides == {}
        assert store.all_defaults_disabled is False

    def test_upsert_and_save_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "skills_overrides.json"
        store = SkillOverrideStore.load(path, scope_label="queen:x")
        store.upsert(
            "foo",
            OverrideEntry(
                enabled=False,
                provenance=Provenance.FRAMEWORK,
                created_at=datetime(2026, 4, 21, tzinfo=UTC),
                created_by="user",
            ),
        )
        store.save()

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert raw["overrides"]["foo"]["enabled"] is False
        assert raw["overrides"]["foo"]["provenance"] == "framework"

        # Re-load preserves values
        again = SkillOverrideStore.load(path, scope_label="queen:x")
        assert again.get("foo") is not None
        assert again.get("foo").enabled is False

    def test_tombstone_survives_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "skills_overrides.json"
        store = SkillOverrideStore.load(path, scope_label="queen:x")
        store.upsert("foo", OverrideEntry(enabled=True, provenance=Provenance.USER_UI_CREATED))
        store.remove("foo", tombstone=True)
        store.save()
        again = SkillOverrideStore.load(path, scope_label="queen:x")
        assert "foo" in again.deleted_ui_skills
        assert again.get("foo") is None

    def test_corrupt_file_loads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "skills_overrides.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = SkillOverrideStore.load(path, scope_label="queen:x")
        assert store.overrides == {}


class TestAuthoring:
    def test_write_and_remove(self, tmp_path: Path) -> None:
        draft, err = build_draft(
            skill_name="demo",
            skill_description="A demo skill",
            skill_body="## Steps\n1. Do it.\n",
            skill_files=[{"path": "notes.md", "content": "notes"}],
        )
        assert err is None
        assert draft is not None
        installed, werr, replaced = write_skill(draft, target_root=tmp_path, replace_existing=True)
        assert werr is None
        assert installed is not None
        assert (installed / "SKILL.md").exists()
        assert (installed / "notes.md").read_text() == "notes"
        assert replaced is False

    def test_reject_absolute_path(self, tmp_path: Path) -> None:
        _, err = build_draft(
            skill_name="demo",
            skill_description="desc",
            skill_body="body",
            skill_files=[{"path": "/etc/passwd", "content": "oops"}],
        )
        assert err is not None
        assert "relative" in err

    def test_reject_traversal(self, tmp_path: Path) -> None:
        _, err = build_draft(
            skill_name="demo",
            skill_description="desc",
            skill_body="body",
            skill_files=[{"path": "../escape.sh", "content": "oops"}],
        )
        assert err is not None

    def test_reject_invalid_name(self, tmp_path: Path) -> None:
        _, err = build_draft(
            skill_name="Demo_Skill",
            skill_description="desc",
            skill_body="body",
        )
        assert err is not None


class TestSkillsManagerOverrides:
    def test_override_disables_framework_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Quarantine user-scope and skip framework-scope discovery by pointing HOME
        # at an empty tmp dir; supply only one "framework" skill manually via an
        # extra scope tagged as framework so the manager sees it.
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fake_fw = tmp_path / "fake_framework"
        _write_skill_file(fake_fw, "hive.fake-protocol", "Fake default")

        overrides_path = tmp_path / "queen_overrides.json"
        store = SkillOverrideStore.load(overrides_path, scope_label="queen:q")
        store.upsert(
            "hive.fake-protocol",
            OverrideEntry(enabled=False, provenance=Provenance.FRAMEWORK),
        )
        store.save()

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="q",
                queen_overrides_path=overrides_path,
                extra_scope_dirs=[ExtraScope(directory=fake_fw, label="framework", priority=0)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()

        names_enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "hive.fake-protocol" not in names_enabled
        # Enumeration (for UI rendering) still returns the hidden entry.
        assert any(s.name == "hive.fake-protocol" for s in mgr.enumerate_skills_with_source())

    def test_queen_disable_applies_to_colony_ui_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Colonies have no override store of their own — the queen's
        store is the single authority, and its entries apply to skills
        discovered from a colony's dir (``colony_ui`` extra scope) too.
        """
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

        colony_skills = tmp_path / "colony_home" / "skills"
        _write_skill_file(colony_skills, "shared-skill")

        queen_overrides = tmp_path / "queen_overrides.json"
        qstore = SkillOverrideStore.load(queen_overrides, scope_label="queen:q")
        qstore.upsert(
            "shared-skill",
            OverrideEntry(enabled=False, provenance=Provenance.USER_UI_CREATED),
        )
        qstore.save()

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="q",
                queen_overrides_path=queen_overrides,
                extra_scope_dirs=[ExtraScope(directory=colony_skills, label="colony_ui", priority=3)],
                project_root=None,
                skip_community_discovery=True,
                skills_config=SkillsConfig(),
                interactive=False,
            )
        )
        mgr.load()
        enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "shared-skill" not in enabled

    def test_preset_scope_is_off_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Preset-scope skills (bundled capability packs) must stay out
        of the catalog until the user explicitly opts in."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fake_presets = tmp_path / "fake_presets"
        _write_skill_file(fake_presets, "hive.x-automation", "X capability pack")
        _write_skill_file(fake_presets, "hive.browser-automation", "Browser pack")

        mgr = SkillsManager(
            SkillsManagerConfig(
                extra_scope_dirs=[ExtraScope(directory=fake_presets, label="preset", priority=1)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()
        enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "hive.x-automation" not in enabled
        assert "hive.browser-automation" not in enabled
        # Enumeration still surfaces them so the UI can offer a toggle.
        enumerated = {s.name for s in mgr.enumerate_skills_with_source()}
        assert "hive.x-automation" in enumerated
        assert "hive.browser-automation" in enumerated

    def test_preset_skill_enabled_via_explicit_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fake_presets = tmp_path / "fake_presets"
        _write_skill_file(fake_presets, "hive.x-automation")

        overrides_path = tmp_path / "queen_overrides.json"
        store = SkillOverrideStore.load(overrides_path, scope_label="queen:q")
        store.upsert(
            "hive.x-automation",
            OverrideEntry(enabled=True, provenance=Provenance.PRESET),
        )
        store.save()

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="q",
                queen_overrides_path=overrides_path,
                extra_scope_dirs=[ExtraScope(directory=fake_presets, label="preset", priority=1)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()
        enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "hive.x-automation" in enabled

    def test_role_default_preset_enabled_in_memory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A preset named in ``default_preset_skills`` is on by default — no
        override file needed — while other presets stay off. This is the
        in-memory parallel to role-default tools."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fake_presets = tmp_path / "fake_presets"
        _write_skill_file(fake_presets, "hive.linkedin-message-campaign", "campaign")
        _write_skill_file(fake_presets, "hive.x-automation", "x pack")

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="queen_outbound",
                default_preset_skills=frozenset({"hive.linkedin-message-campaign"}),
                extra_scope_dirs=[ExtraScope(directory=fake_presets, label="preset", priority=1)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()
        enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "hive.linkedin-message-campaign" in enabled  # role default → on
        assert "hive.x-automation" not in enabled  # other preset → still off

    def test_role_default_preset_disabled_by_explicit_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit enabled=False override beats the role default, so the
        user can always turn a defaulted preset back off."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fake_presets = tmp_path / "fake_presets"
        _write_skill_file(fake_presets, "hive.linkedin-message-campaign", "campaign")

        overrides_path = tmp_path / "queen_overrides.json"
        store = SkillOverrideStore.load(overrides_path, scope_label="queen:queen_outbound")
        store.upsert(
            "hive.linkedin-message-campaign",
            OverrideEntry(enabled=False, provenance=Provenance.PRESET),
        )
        store.save()

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="queen_outbound",
                queen_overrides_path=overrides_path,
                default_preset_skills=frozenset({"hive.linkedin-message-campaign"}),
                extra_scope_dirs=[ExtraScope(directory=fake_presets, label="preset", priority=1)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()
        enabled = {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
        assert "hive.linkedin-message-campaign" not in enabled

    def test_reload_picks_up_store_change(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        fw = tmp_path / "fw"
        _write_skill_file(fw, "alpha")
        path = tmp_path / "queen.json"

        mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id="q",
                queen_overrides_path=path,
                extra_scope_dirs=[ExtraScope(directory=fw, label="framework", priority=0)],
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        mgr.load()
        assert "alpha" in {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]

        # Disable via override file + reload
        store = SkillOverrideStore.load(path, scope_label="queen:q")
        store.upsert("alpha", OverrideEntry(enabled=False, provenance=Provenance.FRAMEWORK))
        store.save()
        mgr.reload()
        assert "alpha" not in {s.name for s in mgr._catalog._skills.values()}  # type: ignore[attr-defined]
