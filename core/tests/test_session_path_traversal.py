"""Tests for path traversal protection in session route handlers.

Verifies that safe_path_segment() — now used by all 13 session_id extraction
points in routes_sessions.py — correctly rejects malicious path traversal
payloads.
"""

import pytest
from aiohttp import web

from framework.server.app import safe_path_segment


class TestSafePathSegment:
    """Verify safe_path_segment rejects traversal payloads."""

    def test_valid_session_id(self):
        assert safe_path_segment("abc123") == "abc123"

    def test_valid_uuid(self):
        assert safe_path_segment("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"

    def test_rejects_empty(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("")

    def test_rejects_dot(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment(".")

    def test_rejects_double_dot(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("..")

    def test_rejects_slash(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("abc/def")

    def test_rejects_backslash(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("abc\\def")

    def test_rejects_traversal_sequence(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("../../etc/passwd")

    def test_rejects_encoded_traversal(self):
        # aiohttp decodes %2F before route matching, so / appears literally
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("../../../tmp")

    def test_rejects_dot_dot_in_middle(self):
        with pytest.raises(web.HTTPBadRequest):
            safe_path_segment("foo/../bar")


class TestSessionRoutesUseSafePathSegment:
    """Verify routes_sessions.py actually calls safe_path_segment.

    This is a code-level assertion — if someone removes the validation,
    this test will catch it.
    """

    def test_all_session_id_extractions_are_validated(self):
        """Every match_info['session_id'] in routes_sessions.py must go through safe_path_segment."""
        import inspect

        from framework.server import routes_sessions

        source = inspect.getsource(routes_sessions)

        # Count raw extractions (unsafe pattern)
        raw_count = source.count('request.match_info["session_id"]')
        # Count validated extractions (safe pattern)
        safe_count = source.count('safe_path_segment(request.match_info["session_id"])')

        assert raw_count > 0, "Expected session_id extractions in routes_sessions"
        assert raw_count == safe_count, (
            f"Found {raw_count} session_id extractions but only {safe_count} "
            f"go through safe_path_segment — {raw_count - safe_count} are unprotected"
        )
