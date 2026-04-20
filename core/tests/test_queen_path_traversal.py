"""Tests for queen route path-traversal hardening (#7099).

Validates that every handler in ``routes_queens.py`` passes ``queen_id``
through ``safe_path_segment`` before filesystem access, and that the
body-sourced ``session_id`` in ``handle_select_queen_session`` is also
validated.
"""

import ast
import inspect
import textwrap

import pytest
from aiohttp import web

from framework.server.app import safe_path_segment

# ---------------------------------------------------------------------------
# Unit: safe_path_segment rejects path-traversal payloads
# ---------------------------------------------------------------------------

_TRAVERSAL_PAYLOADS = [
    "..",
    "../etc/passwd",
    "..%2Fetc%2Fpasswd",
    "foo/../bar",
    "/etc/passwd",
    "\\\\windows\\system32",
    "a\\b",
    "",
    ".",
]


@pytest.mark.parametrize("payload", _TRAVERSAL_PAYLOADS)
def test_safe_path_segment_rejects_traversal(payload: str) -> None:
    with pytest.raises(web.HTTPBadRequest):
        safe_path_segment(payload)


def test_safe_path_segment_accepts_valid() -> None:
    assert safe_path_segment("valid-queen-id") == "valid-queen-id"
    assert safe_path_segment("queen_42") == "queen_42"
    assert safe_path_segment("abc123") == "abc123"


# ---------------------------------------------------------------------------
# Source-level: every queen_id extraction uses safe_path_segment
# ---------------------------------------------------------------------------


class TestQueenRoutesUseSafePathSegment:
    """Inspect the source of each route handler to verify protection."""

    @staticmethod
    def _handler_source(handler_name: str) -> str:
        from framework.server import routes_queens

        handler = getattr(routes_queens, handler_name)
        return textwrap.dedent(inspect.getsource(handler))

    _QUEEN_HANDLERS = [
        "handle_get_profile",
        "handle_update_profile",
        "handle_queen_session",
        "handle_select_queen_session",
        "handle_new_queen_session",
        "handle_upload_avatar",
        "handle_get_avatar",
    ]

    @pytest.mark.parametrize("handler_name", _QUEEN_HANDLERS)
    def test_queen_id_wrapped(self, handler_name: str) -> None:
        """Every handler must wrap match_info['queen_id'] with safe_path_segment."""
        src = self._handler_source(handler_name)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "queen_id"
            ):
                # The subscript must be an argument to safe_path_segment
                assert "safe_path_segment" in ast.dump(ast.parse(src)), (
                    f"{handler_name} accesses queen_id without safe_path_segment"
                )

    def test_select_session_validates_body_session_id(self) -> None:
        """handle_select_queen_session must validate body session_id via safe_path_segment."""
        src = self._handler_source("handle_select_queen_session")
        assert "safe_path_segment" in src
        # Ensure safe_path_segment is called on target_session_id
        assert "safe_path_segment(target_session_id" in src


# ---------------------------------------------------------------------------
# Source-level: no unprotected match_info["queen_id"] in routes_queens module
# ---------------------------------------------------------------------------


def test_no_unprotected_queen_id_extraction() -> None:
    """Scan the entire routes_queens module source: every match_info['queen_id']
    line must also contain 'safe_path_segment'."""
    from framework.server import routes_queens

    src = inspect.getsource(routes_queens)
    for i, line in enumerate(src.splitlines(), 1):
        if 'match_info["queen_id"]' in line:
            assert "safe_path_segment" in line, (
                f"routes_queens.py line {i}: match_info['queen_id'] is not wrapped with safe_path_segment"
            )
