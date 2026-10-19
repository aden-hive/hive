"""Tests for obsidian_tool - Obsidian Local REST API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.obsidian_tool.obsidian_tool import register_tools

ENV = {
    "OBSIDIAN_REST_API_KEY": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    "OBSIDIAN_REST_BASE_URL": "https://127.0.0.1:27124",
}


def _mock_resp(data, status_code=200, content_type="application/json"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.json.return_value = data
    resp.text = str(data) if isinstance(data, str) else ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestObsidianReadNote:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["obsidian_read_note"](path="test.md")
        assert "error" in result

    def test_missing_path(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["obsidian_read_note"](path="")
        assert "error" in result

    def test_successful_read(self, tool_fns):
        data = {
            "content": "# Meeting Notes\n\nDiscussed project roadmap.",
            "path": "Notes/meeting.md",
            "tags": ["meeting", "project"],
            "frontmatter": {"status": "draft"},
            "stat": {"ctime": 1705334400000, "mtime": 1705420800000, "size": 2048},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.obsidian_tool.obsidian_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["obsidian_read_note"](path="Notes/meeting.md")

        assert result["path"] == "Notes/meeting.md"
        assert "Meeting Notes" in result["content"]
        assert "meeting" in result["tags"]


class TestObsidianWriteNote:
    def test_missing_path(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["obsidian_write_note"](path="", content="test")
        assert "error" in result

    def test_successful_write(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 204
        resp.headers = {"content-type": ""}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.obsidian_tool.obsidian_tool.httpx.put", return_value=resp),
        ):
            result = tool_fns["obsidian_write_note"](
                path="Daily/2025-03-03.md",
                content="# March 3\n\n- Morning tasks",
            )

        assert result["success"] is True
        assert result["path"] == "Daily/2025-03-03.md"


class TestObsidianAppendNote:
    def test_successful_append(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 204
        resp.headers = {"content-type": ""}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.obsidian_tool.obsidian_tool.httpx.post", return_value=resp),
        ):
            result = tool_fns["obsidian_append_note"](
                path="Daily/2025-03-03.md",
                content="\n## Afternoon\n- Review PR",
            )

        assert result["success"] is True


class TestObsidianSearch:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["obsidian_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = [
            {
                "filename": "Daily/2025-03-01.md",
                "score": 0.85,
                "matches": [
                    {
                        "match": {"start": 45, "end": 52},
                        "context": "...attended the team meeting to discuss...",
                    },
                    {
                        "match": {"start": 120, "end": 127},
                        "context": "...follow-up meeting scheduled for...",
                    },
                ],
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.obsidian_tool.obsidian_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["obsidian_search"](query="meeting")

        assert result["count"] == 1
        assert result["results"][0]["filename"] == "Daily/2025-03-01.md"
        assert result["results"][0]["match_count"] == 2


class TestObsidianListFiles:
    def test_successful_list(self, tool_fns):
        data = ["Daily/", "Projects/", "README.md", "Templates/"]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.obsidian_tool.obsidian_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["obsidian_list_files"]()

        assert result["count"] == 4
        assert "Daily/" in result["files"]
        assert "README.md" in result["files"]


class TestObsidianGetActive:
    def test_successful_get(self, tool_fns):
        data = {
            "content": "# Current Note\n\nWorking on this.",
            "path": "Projects/current.md",
            "tags": ["active"],
            "frontmatter": {"status": "wip"},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.obsidian_tool.obsidian_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["obsidian_get_active"]()

        assert result["path"] == "Projects/current.md"
        assert "Current Note" in result["content"]

    def test_no_active_file(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 405
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {"message": "No active file"}
        resp.text = ""
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.obsidian_tool.obsidian_tool.httpx.get", return_value=resp),
        ):
            result = tool_fns["obsidian_get_active"]()

        assert "error" in result
