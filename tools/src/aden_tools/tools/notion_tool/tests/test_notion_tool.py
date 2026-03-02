"""Tests for Notion tool."""

from __future__ import annotations
import sys, os
import asyncio # <-- Added this import

# Direct import — bypasses tools/__init__.py and all other tool deps
sys.path.insert(0, "/content/hive/tools/src")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "notion_tool",
    "/content/hive/tools/src/aden_tools/tools/notion_tool/notion_tool.py"
)
mod = importlib.util.load_from_spec = None  # not used
notion_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notion_mod)

_NotionClient = notion_mod._NotionClient
_blocks_to_text = notion_mod._blocks_to_text
_build_block = notion_mod._build_block
_extract_page_title = notion_mod._extract_page_title
_rich_text = notion_mod._rich_text
register_tools = notion_mod.register_tools
NOTION_API_BASE = notion_mod.NOTION_API_BASE

from unittest.mock import MagicMock, patch
import pytest


class TestRichText:
    def test_basic(self):
        r = _rich_text("hello")
        assert r == [{"type": "text", "text": {"content": "hello"}}]

    def test_truncated_at_2000(self):
        r = _rich_text("x" * 3000)
        assert len(r[0]["text"]["content"]) == 2000


class TestBuildBlock:
    def test_paragraph(self):
        b = _build_block("paragraph", "Hello")
        assert b["type"] == "paragraph"
        assert b["paragraph"]["rich_text"][0]["text"]["content"] == "Hello"

    def test_to_do_checked(self):
        b = _build_block("to_do", "Done", checked=True)
        assert b["to_do"]["checked"] is True

    def test_to_do_unchecked(self):
        b = _build_block("to_do", "Task", checked=False)
        assert b["to_do"]["checked"] is False

    def test_heading_2(self):
        b = _build_block("heading_2", "Section")
        assert b["type"] == "heading_2"


class TestBlocksToText:
    def _block(self, btype, text, **extra):
        base = {"type": btype, btype: {"rich_text": [{"plain_text": text}]}}
        base[btype].update(extra)
        return base

    def test_paragraph(self):
        assert _blocks_to_text([self._block("paragraph", "Hi")]) == "Hi"

    def test_heading_1(self):
        assert _blocks_to_text([self._block("heading_1", "T")]) == "# T"

    def test_heading_2(self):
        assert _blocks_to_text([self._block("heading_2", "S")]) == "## S"

    def test_heading_3(self):
        assert _blocks_to_text([self._block("heading_3", "D")]) == "### D"

    def test_bulleted(self):
        assert _blocks_to_text([self._block("bulleted_list_item", "X")]) == "• X"

    def test_divider(self):
        assert _blocks_to_text([{"type": "divider", "divider": {}}]) == "---"

    def test_empty(self):
        assert _blocks_to_text([]) == ""

    def test_multiple(self):
        blocks = [self._block("heading_1", "Title"), self._block("paragraph", "Body")]
        result = _blocks_to_text(blocks)
        assert "# Title" in result and "Body" in result


class TestExtractPageTitle:
    def test_standard(self):
        page = {"id": "x", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "My Page"}]}
        }}
        assert _extract_page_title(page) == "My Page"

    def test_fallback_to_id(self):
        page = {"id": "abc", "properties": {"Status": {"type": "select"}}}
        assert _extract_page_title(page) == "abc"

    def test_empty_title(self):
        page = {"id": "xyz", "properties": {"title": {"type": "title", "title": []}}}
        assert _extract_page_title(page) == ""


class TestNotionClient:
    def setup_method(self):
        self.client = _NotionClient("test-key")

    def _resp(self, status, data):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = data
        return r

    def test_headers(self):
        assert self.client._headers["Authorization"] == "Bearer test-key"
        assert "Notion-Version" in self.client._headers

    def test_200(self):
        assert self.client._handle_response(self._resp(200, {"ok": True})) == {"ok": True}

    @pytest.mark.parametrize("code,fragment", [
        (401, "Invalid Notion"),
        (403, "lacks permission"),
        (404, "not found"),
        (429, "rate limit"),
    ])
    def test_errors(self, code, fragment):
        r = self.client._handle_response(self._resp(code, {}))
        assert "error" in r and fragment.lower() in r["error"].lower()

    def test_500(self):
        r = self.client._handle_response(self._resp(500, {"message": "boom"}))
        assert "error" in r and "500" in r["error"]

    @patch("httpx.post")
    def test_search(self, mock_post):
        mock_post.return_value = self._resp(200, {"results": []})
        assert "results" in self.client.search("hello")

    @patch("httpx.get")
    def test_get_page(self, mock_get):
        mock_get.return_value = self._resp(200, {"id": "p1"})
        assert self.client.get_page("p1")["id"] == "p1"

    @patch("httpx.get")
    def test_timeout(self, mock_get):
        import httpx as _h
        mock_get.side_effect = _h.TimeoutException("t")
        assert "timed out" in self.client.get_page("p1")["error"]

    @patch("httpx.patch")
    def test_append_blocks(self, mock_patch):
        mock_patch.return_value = self._resp(200, {"results": []})
        result = self.client.append_blocks("b1", [{"type": "paragraph"}])
        assert "error" not in result

    @patch("httpx.post")
    def test_create_page(self, mock_post):
        mock_post.return_value = self._resp(200,
            {"id": "new-id", "url": "https://notion.so/new", "created": True})
        result = self.client.create_page({"type": "page_id", "page_id": "p1"}, {}, [])
        assert result["id"] == "new-id" and result["created"] is True

    @patch("httpx.post")
    def test_query_database(self, mock_post):
        mock_post.return_value = self._resp(200, {"results": [], "has_more": False})
        assert "results" in self.client.query_database("db-1")


class TestMCPTools:
    def setup_method(self):
        from fastmcp import FastMCP
        self.mcp = FastMCP("test")
        register_tools(self.mcp)

        # Helper to run async get_tool in a synchronous context
        async def _get_tool_fn_async(tool_name):
            tool_obj = await self.mcp.get_tool(tool_name)
            return tool_obj.fn

        # Use asyncio.run to execute the async helper in the sync setup_method
        self.search = asyncio.run(_get_tool_fn_async("notion_search"))
        self.read   = asyncio.run(_get_tool_fn_async("notion_read_page"))
        self.create = asyncio.run(_get_tool_fn_async("notion_create_page"))
        self.append = asyncio.run(_get_tool_fn_async("notion_append_to_page"))
        self.query  = asyncio.run(_get_tool_fn_async("notion_query_database"))

    def test_search_no_key(self):
        with patch.dict("os.environ", {}, clear=True):
            os.environ.pop("NOTION_API_KEY", None)
            assert "error" in self.search("test")

    def test_search_empty_query(self):
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            assert "error" in self.search("")

    def test_read_missing_id(self):
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            assert "error" in self.read("")

    def test_create_missing_title(self):
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            assert "error" in self.create("parent", "")

    def test_append_missing_content(self):
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            assert "error" in self.append("page", "")

    def test_query_missing_id(self):
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            assert "error" in self.query("")

    @patch("httpx.get")
    @patch("httpx.post")
    def test_read_page_flow(self, mock_post, mock_get):
        page_r = MagicMock(status_code=200, json=lambda: {
            "id": "p1", "object": "page", "url": "https://notion.so/p1",
            "properties": {"title": {"type": "title", "title": [{"plain_text": "Test"}]}},
        })
        blocks_r = MagicMock(status_code=200, json=lambda: {"results": [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}}
        ]})
        mock_get.side_effect = [page_r, blocks_r]
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            r = self.read("p1")
        assert r["title"] == "Test"
        assert "Hello world" in r["content"]

    @patch("httpx.post")
    def test_search_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"results": [
            {"id": "abc", "object": "page", "url": "https://notion.so/abc",
             "last_edited_time": "2024-01-01",
             "properties": {"title": {"type": "title", "title": [{"plain_text": "My Note"}]}}}
        ]})
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            r = self.search("My Note")
        assert r["total"] == 1 and r["results"][0]["title"] == "My Note"

    @patch("httpx.post")
    def test_create_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200,
            json=lambda: {"id": "new-id", "url": "https://notion.so/new"})
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            r = self.create("parent", "New Doc", content="Hello")
        assert r["id"] == "new-id" and r["created"] is True

    @patch("httpx.post")
    def test_query_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {
            "results": [{"id": "e1", "object": "page", "url": "https://notion.so/e1",
                         "last_edited_time": "2024-01-02", "created_time": "2024-01-01",
                         "properties": {"Name": {"type": "title",
                                                  "title": [{"plain_text": "Task 1"}]}}}],
            "has_more": False
        })
        with patch.dict("os.environ", {"NOTION_API_KEY": "fake"}):
            r = self.query("db-123")
        assert r["total"] == 1 and r["entries"][0]["title"] == "Task 1"

print("✅ Test file rewritten with direct imports")