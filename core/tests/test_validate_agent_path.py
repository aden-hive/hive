"""Tests for validate_agent_path() and _get_allowed_agent_roots().

Verifies the allowlist-based path validation that prevents arbitrary code
execution via importlib.import_module() (Issue #5471).
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.server.app import (
    _get_allowed_agent_roots,
    create_app,
    validate_agent_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_allowed_roots():
    """Reset the cached _ALLOWED_AGENT_ROOTS so tests start fresh."""
    import framework.server.app as app_module

    app_module._ALLOWED_AGENT_ROOTS = None


# ---------------------------------------------------------------------------
# _get_allowed_agent_roots
# ---------------------------------------------------------------------------


class TestGetAllowedAgentRoots:
    def setup_method(self):
        _reset_allowed_roots()

    def teardown_method(self):
        _reset_allowed_roots()

    def test_returns_tuple(self):
        roots = _get_allowed_agent_roots()
        assert isinstance(roots, tuple), f"Expected tuple, got {type(roots).__name__}"

    def test_contains_three_roots(self):
        roots = _get_allowed_agent_roots()
        assert len(roots) == 3

    def test_cached_on_repeated_calls(self):
        first = _get_allowed_agent_roots()
        second = _get_allowed_agent_roots()
        assert first is second

    def test_roots_are_resolved_paths(self):
        for root in _get_allowed_agent_roots():
            assert root.is_absolute()
            # A resolved path has no '..' components
            assert ".." not in root.parts

    def test_roots_anchored_to_repo_not_cwd(self):
        """exports/ and examples/ should be relative to the repo root
        (derived from __file__), not the process CWD."""
        from framework.server.app import _REPO_ROOT

        roots = _get_allowed_agent_roots()
        exports_root, examples_root = roots[0], roots[1]
        assert exports_root == (_REPO_ROOT / "exports").resolve()
        assert examples_root == (_REPO_ROOT / "examples").resolve()


# ---------------------------------------------------------------------------
# validate_agent_path: positive cases (should return resolved Path)
# ---------------------------------------------------------------------------


class TestValidateAgentPathPositive:
    def setup_method(self):
        _reset_allowed_roots()

    def teardown_method(self):
        _reset_allowed_roots()

    def test_path_inside_exports(self, tmp_path):
        with patch("framework.server.app._ALLOWED_AGENT_ROOTS", None):
            import framework.server.app as app_module

            agent_dir = tmp_path / "my_agent"
            agent_dir.mkdir()
            app_module._ALLOWED_AGENT_ROOTS = (tmp_path,)
            result = validate_agent_path(str(agent_dir))
            assert result == agent_dir.resolve()

    def test_path_inside_examples(self, tmp_path):
        import framework.server.app as app_module

        examples_root = tmp_path / "examples"
        examples_root.mkdir()
        agent_dir = examples_root / "some_agent"
        agent_dir.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (examples_root,)
        result = validate_agent_path(str(agent_dir))
        assert result == agent_dir.resolve()

    def test_path_inside_hive_agents(self, tmp_path):
        import framework.server.app as app_module

        hive_root = tmp_path / ".hive" / "agents"
        hive_root.mkdir(parents=True)
        agent_dir = hive_root / "my_agent"
        agent_dir.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (hive_root,)
        result = validate_agent_path(str(agent_dir))
        assert result == agent_dir.resolve()

    def test_returns_path_object(self, tmp_path):
        import framework.server.app as app_module

        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (tmp_path,)
        result = validate_agent_path(str(agent_dir))
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# validate_agent_path: negative cases (should raise ValueError)
# ---------------------------------------------------------------------------


class TestValidateAgentPathNegative:
    def setup_method(self):
        _reset_allowed_roots()

    def teardown_method(self):
        _reset_allowed_roots()

    def _set_roots(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir(exist_ok=True)
        app_module._ALLOWED_AGENT_ROOTS = (exports,)

    def test_absolute_path_outside_roots(self, tmp_path):
        self._set_roots(tmp_path)
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path("/tmp/evil")

    def test_traversal_escape(self, tmp_path):
        self._set_roots(tmp_path)
        exports = tmp_path / "exports"
        traversal = str(exports / ".." / ".." / "tmp" / "evil")
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path(traversal)

    def test_sibling_directory_name(self, tmp_path):
        self._set_roots(tmp_path)
        # "exports-evil" is NOT a child of "exports"
        sibling = tmp_path / "exports-evil" / "agent"
        sibling.mkdir(parents=True)
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path(str(sibling))

    def test_empty_string(self, tmp_path):
        self._set_roots(tmp_path)
        # Empty string resolves to CWD, which is outside the allowed roots
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path("")

    def test_home_directory(self, tmp_path):
        self._set_roots(tmp_path)
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path("~")

    def test_root(self, tmp_path):
        self._set_roots(tmp_path)
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path("/")

    def test_null_byte(self, tmp_path):
        """Null bytes in paths must be rejected (pathlib raises ValueError)."""
        self._set_roots(tmp_path)
        with pytest.raises(ValueError):
            validate_agent_path("exports/\x00evil")

    def test_symlink_escape(self, tmp_path):
        """A symlink inside an allowed root pointing outside must be rejected."""
        import framework.server.app as app_module

        allowed = tmp_path / "exports"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = allowed / "sneaky"
        link.symlink_to(outside)
        app_module._ALLOWED_AGENT_ROOTS = (allowed,)
        # The symlink resolves to outside the allowed root
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path(str(link))

    def test_root_itself_rejected(self, tmp_path):
        """Passing the exact root directory itself should be rejected."""
        import framework.server.app as app_module

        allowed = tmp_path / "exports"
        allowed.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (allowed,)
        with pytest.raises(ValueError, match="allowed directory"):
            validate_agent_path(str(allowed))

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        """Paths with ~ prefix should be expanded via expanduser()."""
        import framework.server.app as app_module

        # Set both HOME (POSIX) and USERPROFILE (Windows) so
        # Path.expanduser() resolves ~ to tmp_path on all platforms.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        hive_agents = tmp_path / ".hive" / "agents"
        hive_agents.mkdir(parents=True)
        agent_dir = hive_agents / "my_agent"
        agent_dir.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (hive_agents,)

        result = validate_agent_path("~/.hive/agents/my_agent")
        assert result == agent_dir.resolve()


# ---------------------------------------------------------------------------
# _ALLOWED_AGENT_ROOTS immutability
# ---------------------------------------------------------------------------


class TestAllowedRootsImmutability:
    def setup_method(self):
        _reset_allowed_roots()

    def teardown_method(self):
        _reset_allowed_roots()

    def test_is_tuple_not_list(self):
        roots = _get_allowed_agent_roots()
        assert isinstance(roots, tuple), "Should be tuple to prevent mutation"
        assert not isinstance(roots, list)


# ---------------------------------------------------------------------------
# Integration tests: HTTP endpoints reject malicious paths
# ---------------------------------------------------------------------------


class TestHTTPEndpointsRejectMaliciousPaths:
    """Test that HTTP route handlers return 400 for paths outside allowed roots."""

    @pytest.mark.asyncio
    async def test_create_session_rejects_outside_path(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (exports,)
        try:
            app = create_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/sessions",
                    json={"agent_path": "/tmp/evil"},
                )
                assert resp.status == 400
                body = await resp.json()
                assert "allowed directory" in body["error"]
        finally:
            _reset_allowed_roots()

    @pytest.mark.asyncio
    async def test_create_session_rejects_traversal(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (exports,)
        try:
            app = create_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/sessions",
                    json={"agent_path": "exports/../../tmp/evil"},
                )
                assert resp.status == 400
                body = await resp.json()
                assert "allowed directory" in body["error"]
        finally:
            _reset_allowed_roots()

    @pytest.mark.asyncio
    async def test_load_worker_rejects_outside_path(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (exports,)
        try:
            app = create_app()
            async with TestClient(TestServer(app)) as client:
                # First create a queen-only session
                create_resp = await client.post("/api/sessions", json={})
                if create_resp.status != 201:
                    pytest.skip(f"Cannot create queen-only session (status={create_resp.status})")
                session_id = (await create_resp.json())["session_id"]

                resp = await client.post(
                    f"/api/sessions/{session_id}/worker",
                    json={"agent_path": "/tmp/evil"},
                )
                assert resp.status == 400
                body = await resp.json()
                assert "allowed directory" in body["error"]
        finally:
            _reset_allowed_roots()

    @pytest.mark.asyncio
    async def test_check_agent_credentials_rejects_traversal(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (exports,)
        try:
            app = create_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/credentials/check-agent",
                    json={"agent_path": "exports/../../etc/passwd"},
                )
                assert resp.status == 400
                body = await resp.json()
                assert "allowed directory" in body["error"]
        finally:
            _reset_allowed_roots()

    @pytest.mark.asyncio
    async def test_error_message_does_not_leak_resolved_path(self, tmp_path):
        import framework.server.app as app_module

        exports = tmp_path / "exports"
        exports.mkdir()
        app_module._ALLOWED_AGENT_ROOTS = (exports,)
        try:
            app = create_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/sessions",
                    json={"agent_path": "/tmp/evil"},
                )
                body = await resp.json()
                # The error message should not contain the resolved absolute path
                # It should use the generic allowlist message
                assert "/tmp/evil" not in body["error"]
                assert "allowed directory" in body["error"]
        finally:
            _reset_allowed_roots()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
