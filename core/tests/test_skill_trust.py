"""Tests for skill trust gating (AS-13)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from framework.skills.parser import ParsedSkill
from framework.skills.trust import (
    ProjectTrustClassification,
    ProjectTrustDetector,
    TrustedRepoStore,
    TrustGate,
    _is_localhost_remote,
    _normalize_remote_url,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_skill(name: str = "test-skill", scope: str = "project") -> ParsedSkill:
    return ParsedSkill(
        name=name,
        description="Test skill",
        location=f"/fake/{name}/SKILL.md",
        base_dir=f"/fake/{name}",
        source_scope=scope,
        body="Test skill instructions.",
    )


# ---------------------------------------------------------------------------
# _normalize_remote_url
# ---------------------------------------------------------------------------


class TestNormalizeRemoteUrl:
    def test_ssh_scp_format(self):
        assert _normalize_remote_url("git@github.com:org/repo.git") == "github.com/org/repo"

    def test_https_format(self):
        assert _normalize_remote_url("https://github.com/org/repo.git") == "github.com/org/repo"

    def test_https_no_dot_git(self):
        assert _normalize_remote_url("https://github.com/org/repo") == "github.com/org/repo"

    def test_ssh_url_format(self):
        assert _normalize_remote_url("ssh://git@github.com/org/repo.git") == "github.com/org/repo"

    def test_lowercased(self):
        assert _normalize_remote_url("git@GitHub.COM:Org/Repo.git") == "github.com/org/repo"

    def test_trailing_slash_stripped(self):
        assert _normalize_remote_url("https://github.com/org/repo/") == "github.com/org/repo"

    def test_gitlab(self):
        assert _normalize_remote_url("git@gitlab.com:team/project.git") == "gitlab.com/team/project"


# ---------------------------------------------------------------------------
# _is_localhost_remote
# ---------------------------------------------------------------------------


class TestIsLocalhostRemote:
    def test_localhost_https(self):
        assert _is_localhost_remote("http://localhost/org/repo")

    def test_127_0_0_1(self):
        assert _is_localhost_remote("https://127.0.0.1/repo")

    def test_github_not_local(self):
        assert not _is_localhost_remote("https://github.com/org/repo")

    def test_scp_localhost(self):
        assert _is_localhost_remote("git@localhost:org/repo")


# ---------------------------------------------------------------------------
# TrustedRepoStore
# ---------------------------------------------------------------------------


class TestTrustedRepoStore:
    def test_empty_store_is_not_trusted(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "trusted.json")
        assert not store.is_trusted("github.com/org/repo")

    def test_trust_and_lookup(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "trusted.json")
        store.trust("github.com/org/repo", project_path="/some/path")
        assert store.is_trusted("github.com/org/repo")

    def test_revoke(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "trusted.json")
        store.trust("github.com/org/repo")
        assert store.revoke("github.com/org/repo")
        assert not store.is_trusted("github.com/org/repo")

    def test_revoke_nonexistent_returns_false(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "trusted.json")
        assert not store.revoke("github.com/nobody/nowhere")

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "trusted.json"
        store1 = TrustedRepoStore(path)
        store1.trust("github.com/org/repo")

        store2 = TrustedRepoStore(path)
        assert store2.is_trusted("github.com/org/repo")

    def test_atomic_write(self, tmp_path):
        """Save must not leave a .tmp file behind."""
        path = tmp_path / "trusted.json"
        store = TrustedRepoStore(path)
        store.trust("github.com/org/repo")
        assert not (tmp_path / "trusted.tmp").exists()
        assert path.exists()

    def test_corrupted_json_recovers_gracefully(self, tmp_path):
        path = tmp_path / "trusted.json"
        path.write_text("{not valid json{{", encoding="utf-8")
        store = TrustedRepoStore(path)
        assert not store.is_trusted("github.com/any/repo")  # no crash

    def test_json_schema(self, tmp_path):
        path = tmp_path / "trusted.json"
        store = TrustedRepoStore(path)
        store.trust("github.com/org/repo", project_path="/work/repo")
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["entries"][0]["repo_key"] == "github.com/org/repo"
        assert "added_at" in data["entries"][0]

    def test_list_entries(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "t.json")
        store.trust("github.com/a/b")
        store.trust("github.com/c/d")
        entries = store.list_entries()
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# ProjectTrustDetector
# ---------------------------------------------------------------------------


class TestProjectTrustDetector:
    def test_none_project_dir_always_trusted(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        cls, _ = det.classify(None)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_nonexistent_dir_always_trusted(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        cls, _ = det.classify(tmp_path / "nonexistent")
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_no_git_dir_always_trusted(self, tmp_path):
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_no_remote_always_trusted(self, tmp_path):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        # git command returns non-zero (no remote)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_localhost_remote_always_trusted(self, tmp_path):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="http://localhost/org/repo.git\n")
            cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_trusted_by_store(self, tmp_path):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        store.trust("github.com/trusted/repo")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="git@github.com:trusted/repo.git\n")
            cls, key = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.TRUSTED_BY_USER
        assert key == "github.com/trusted/repo"

    def test_unknown_remote_untrusted(self, tmp_path):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            cls, key = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.UNTRUSTED
        assert key == "github.com/stranger/repo"

    def test_own_remotes_env_var(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        monkeypatch.setenv("HIVE_OWN_REMOTES", "github.com/myorg/*")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="git@github.com:myorg/myrepo.git\n")
            cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_git_timeout_treated_as_trusted(self, tmp_path):
        import subprocess

        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 3)):
            cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED

    def test_git_not_found_treated_as_trusted(self, tmp_path):
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        det = ProjectTrustDetector(store)
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            cls, _ = det.classify(tmp_path)
        assert cls == ProjectTrustClassification.ALWAYS_TRUSTED


# ---------------------------------------------------------------------------
# TrustGate
# ---------------------------------------------------------------------------


class TestTrustGate:
    def test_framework_scope_always_passes(self, tmp_path):
        skill = make_skill("fw-skill", "framework")
        gate = TrustGate(store=TrustedRepoStore(tmp_path / "t.json"), interactive=False)
        result = gate.filter_and_gate([skill], project_dir=None)
        assert any(s.name == "fw-skill" for s in result)

    def test_user_scope_always_passes(self, tmp_path):
        skill = make_skill("user-skill", "user")
        gate = TrustGate(store=TrustedRepoStore(tmp_path / "t.json"), interactive=False)
        result = gate.filter_and_gate([skill], project_dir=None)
        assert any(s.name == "user-skill" for s in result)

    def test_no_project_skills_returns_early(self, tmp_path):
        """When there are no project-scope skills, trust detection is skipped."""
        fw = make_skill("fw", "framework")
        gate = TrustGate(store=TrustedRepoStore(tmp_path / "t.json"), interactive=False)
        result = gate.filter_and_gate([fw], project_dir=tmp_path)
        assert result == [fw]

    def test_trusted_project_skills_pass(self, tmp_path):
        """Project skills from a trusted repo pass through."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        store.trust("github.com/trusted/repo")
        skill = make_skill("proj-skill", "project")
        gate = TrustGate(store=store, interactive=False)
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="git@github.com:trusted/repo.git\n")
            result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert any(s.name == "proj-skill" for s in result)

    def test_untrusted_headless_skips_and_logs(self, tmp_path, caplog):
        """In non-interactive mode, untrusted project skills are skipped."""
        import logging

        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("evil-skill", "project")
        gate = TrustGate(store=store, interactive=False)
        with patch("subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/evil.git\n")
            with caplog.at_level(logging.WARNING):
                result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert not any(s.name == "evil-skill" for s in result)
        assert "untrusted" in caplog.text.lower() or "skipping" in caplog.text.lower()

    def test_interactive_consent_session_only(self, tmp_path):
        """Option 1 (session only) includes skills without writing to store."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("session-skill", "project")
        outputs = []
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=outputs.append,
            input_fn=lambda _: "1",  # trust this session
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert any(s.name == "session-skill" for s in result)
        # Must NOT persist to trusted store
        assert not store.is_trusted("github.com/stranger/repo")

    def test_interactive_consent_permanent(self, tmp_path):
        """Option 2 (permanent) includes skills and persists to trusted store."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("perm-skill", "project")
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=lambda _: None,
            input_fn=lambda _: "2",  # trust permanently
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert any(s.name == "perm-skill" for s in result)
        assert store.is_trusted("github.com/stranger/repo")

    def test_interactive_consent_deny(self, tmp_path):
        """Option 3 (deny) excludes project skills."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("bad-skill", "project")
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=lambda _: None,
            input_fn=lambda _: "3",  # deny
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert not any(s.name == "bad-skill" for s in result)

    def test_env_var_override_trusts_all(self, tmp_path, monkeypatch):
        """HIVE_TRUST_PROJECT_SKILLS=1 bypasses gating entirely."""
        monkeypatch.setenv("HIVE_TRUST_PROJECT_SKILLS", "1")
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("env-skill", "project")
        gate = TrustGate(store=store, interactive=False)
        result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert any(s.name == "env-skill" for s in result)

    def test_keyboard_interrupt_treated_as_deny(self, tmp_path):
        """Ctrl-C during consent prompt should deny cleanly."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("interrupted-skill", "project")
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=lambda _: None,
            input_fn=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            result = gate.filter_and_gate([skill], project_dir=tmp_path)
        assert not any(s.name == "interrupted-skill" for s in result)

    def test_security_notice_shown_once(self, tmp_path, monkeypatch):
        """Security notice (NFR-5) should be shown the first time only."""
        # Use a temp sentinel path
        sentinel = tmp_path / ".skill_trust_notice_shown"
        monkeypatch.setattr("framework.skills.trust._NOTICE_SENTINEL_PATH", sentinel)
        assert not sentinel.exists()

        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        skill = make_skill("notice-skill", "project")
        output_lines: list[str] = []
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=output_lines.append,
            input_fn=lambda _: "3",
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            gate.filter_and_gate([skill], project_dir=tmp_path)

        assert sentinel.exists()
        assert any("Security notice" in line for line in output_lines)

        # Second run should NOT show the notice again
        output_lines.clear()
        skill2 = make_skill("notice-skill-2", "project")
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            gate.filter_and_gate([skill2], project_dir=tmp_path)

        assert not any("Security notice" in line for line in output_lines)

    def test_mixed_scopes_only_project_gated(self, tmp_path, monkeypatch):
        """Framework and user skills should pass through even if project skills are denied."""
        (tmp_path / ".git").mkdir()
        store = TrustedRepoStore(tmp_path / "t.json")
        fw_skill = make_skill("fw", "framework")
        user_skill = make_skill("usr", "user")
        proj_skill = make_skill("proj", "project")
        gate = TrustGate(
            store=store,
            interactive=True,
            print_fn=lambda _: None,
            input_fn=lambda _: "3",  # deny project skills
        )
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("subprocess.run") as m,
        ):
            m.return_value = MagicMock(returncode=0, stdout="https://github.com/stranger/repo.git\n")
            result = gate.filter_and_gate([fw_skill, user_skill, proj_skill], project_dir=tmp_path)
        names = {s.name for s in result}
        assert "fw" in names
        assert "usr" in names
        assert "proj" not in names
