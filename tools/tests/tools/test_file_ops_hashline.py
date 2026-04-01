"""Tests for hashline support in file_ops (coder tools)."""

import json
import os
import sys
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.hashline import compute_line_hash


def _anchor(line_num, line_text):
    """Build an anchor string N:hhhh."""
    return f"{line_num}:{compute_line_hash(line_text)}"


@pytest.fixture
def tools(tmp_path):
    """Register file_ops tools with tmp_path as project root."""
    from aden_tools.file_ops import register_file_tools

    mcp = FastMCP("test-server")
    write_calls = []

    def _resolve(p):
        return str(tmp_path / p)

    def _before_write():
        write_calls.append(1)

    register_file_tools(
        mcp,
        resolve_path=_resolve,
        before_write=_before_write,
        project_root=str(tmp_path),
    )
    tool_map = {name: t.fn for name, t in mcp._tool_manager._tools.items()}
    return tool_map, write_calls


# ── read_file hashline ────────────────────────────────────────────────────


class TestReadFileHashline:
    def test_hashline_format(self, tools, tmp_path):
        """hashline=True returns N:hhhh|content format."""
        read_file = tools[0]["read_file"]
        (tmp_path / "f.txt").write_text("hello\nworld\n")

        result = read_file(path="f.txt", hashline=True)
        lines = result.strip().split("\n")
        # First two lines should be hashline formatted
        h1 = compute_line_hash("hello")
        h2 = compute_line_hash("world")
        assert lines[0] == f"1:{h1}|hello"
        assert lines[1] == f"2:{h2}|world"

    def test_hashline_false_unchanged(self, tools, tmp_path):
        """Default (hashline=False) returns standard line-number format."""
        read_file = tools[0]["read_file"]
        (tmp_path / "f.txt").write_text("hello\n")

        result = read_file(path="f.txt", hashline=False)
        # Standard format uses tab-separated line numbers
        assert "\t" in result
        assert "hello" in result

    def test_hashline_offset_limit(self, tools, tmp_path):
        """offset and limit work in hashline mode."""
        read_file = tools[0]["read_file"]
        lines = [f"line{i}" for i in range(1, 11)]
        (tmp_path / "f.txt").write_text("\n".join(lines) + "\n")

        result = read_file(path="f.txt", offset=3, limit=2, hashline=True)
        output_lines = [ln for ln in result.split("\n") if ln and not ln.startswith("(")]
        assert len(output_lines) == 2
        h3 = compute_line_hash("line3")
        assert output_lines[0] == f"3:{h3}|line3"

    def test_hashline_no_line_truncation(self, tools, tmp_path):
        """hashline mode doesn't truncate long lines (would corrupt hashes)."""
        read_file = tools[0]["read_file"]
        long_line = "x" * 3000
        (tmp_path / "f.txt").write_text(long_line + "\n")

        result = read_file(path="f.txt", hashline=True)
        h = compute_line_hash(long_line)
        assert f"1:{h}|{long_line}" in result


# ── search_files hashline ─────────────────────────────────────────────────


class TestSearchFilesHashline:
    def test_hashline_in_results(self, tools, tmp_path):
        """hashline=True adds hash anchors to search results."""
        search_files = tools[0]["search_files"]
        (tmp_path / "f.py").write_text("def foo():\n    pass\n")

        result = search_files(pattern="def foo", path=".", hashline=True)
        # Result should contain hash anchor
        h = compute_line_hash("def foo():")
        assert h in result
        assert f":{h}|" in result

    def test_hashline_false_unchanged(self, tools, tmp_path):
        """Default search has no hash anchors."""
        search_files = tools[0]["search_files"]
        (tmp_path / "f.py").write_text("def foo():\n    pass\n")

        result = search_files(pattern="def foo", path=".", hashline=False)
        h = compute_line_hash("def foo():")
        assert f":{h}|" not in result


# ── hashline_edit ─────────────────────────────────────────────────────────


class TestHashlineEditBasic:
    def test_returns_string(self, tools, tmp_path):
        """hashline_edit returns a string, not a dict."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert isinstance(result, str)
        assert "Applied" in result

    def test_calls_before_write(self, tools, tmp_path):
        """hashline_edit calls the before_write hook."""
        hashline_edit = tools[0]["hashline_edit"]
        write_calls = tools[1]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        hashline_edit(path="f.txt", edits=edits)
        assert len(write_calls) == 1

    def test_invalid_json(self, tools, tmp_path):
        """Invalid JSON returns error string."""
        hashline_edit = tools[0]["hashline_edit"]
        (tmp_path / "f.txt").write_text("aaa\n")
        result = hashline_edit(path="f.txt", edits="not json")
        assert "Error" in result
        assert "Invalid JSON" in result

    def test_empty_edits(self, tools, tmp_path):
        """Empty edits array returns error."""
        hashline_edit = tools[0]["hashline_edit"]
        (tmp_path / "f.txt").write_text("aaa\n")
        result = hashline_edit(path="f.txt", edits="[]")
        assert "Error" in result
        assert "empty" in result

    def test_file_not_found(self, tools, tmp_path):
        """Missing file returns error."""
        hashline_edit = tools[0]["hashline_edit"]
        edits = json.dumps([{"op": "set_line", "anchor": "1:abcd", "content": "x"}])
        result = hashline_edit(path="nope.txt", edits=edits)
        assert "Error" in result
        assert "not found" in result


class TestHashlineEditSetLine:
    def test_set_line(self, tools, tmp_path):
        """set_line replaces a single line."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nBBB\nccc\n"

    def test_set_line_hash_mismatch(self, tools, tmp_path):
        """set_line with wrong hash returns error."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": "2:ffff", "content": "BBB"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Error" in result
        assert "mismatch" in result.lower()

    def test_set_line_delete(self, tools, tmp_path):
        """set_line with empty content deletes the line."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": ""}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nccc\n"


class TestHashlineEditReplaceLines:
    def test_replace_lines(self, tools, tmp_path):
        """replace_lines replaces a range."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "XXX\nYYY\nZZZ",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nXXX\nYYY\nZZZ\nddd\n"


class TestHashlineEditInsert:
    def test_insert_after(self, tools, tmp_path):
        """insert_after adds lines after the anchor."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "insert_after",
                    "anchor": _anchor(1, "aaa"),
                    "content": "NEW",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nNEW\nbbb\nccc\n"

    def test_insert_before(self, tools, tmp_path):
        """insert_before adds lines before the anchor."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "insert_before",
                    "anchor": _anchor(2, "bbb"),
                    "content": "NEW",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nNEW\nbbb\nccc\n"


class TestHashlineEditReplace:
    def test_replace(self, tools, tmp_path):
        """replace does string replacement."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace",
                    "old_content": "bbb",
                    "new_content": "BBB",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nBBB\nccc\n"

    def test_replace_not_found(self, tools, tmp_path):
        """replace with missing old_content returns error."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace",
                    "old_content": "zzz",
                    "new_content": "ZZZ",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Error" in result
        assert "not found" in result


class TestHashlineEditAppend:
    def test_append(self, tools, tmp_path):
        """append adds content at end of file."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "append", "content": "ccc\nddd"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        assert f.read_text() == "aaa\nbbb\nccc\nddd\n"


class TestHashlineEditOverlap:
    def test_overlapping_edits_rejected(self, tools, tmp_path):
        """Overlapping splice ranges are rejected."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"},
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "XXX",
                },
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Error" in result
        assert "Overlapping" in result


class TestHashlineEditAutoCleanup:
    def test_strips_hashline_prefix_multiline(self, tools, tmp_path):
        """auto_cleanup strips N:hhhh| prefixes from multi-line content."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        h_bbb = compute_line_hash("bbb")
        h_ccc = compute_line_hash("ccc")
        # LLM echoes hashline prefixes in replace_lines content
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": f"2:{h_bbb}|BBB\n3:{h_ccc}|CCC",
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Applied 1 edit" in result
        # Should have stripped the prefixes
        assert f.read_text() == "aaa\nBBB\nCCC\nddd\n"
        assert "cleanup" in result.lower()

    def test_no_cleanup_when_disabled(self, tools, tmp_path):
        """auto_cleanup=False writes content as-is."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        h = compute_line_hash("bbb")
        raw_content = f"2:{h}|BBB"
        edits = json.dumps(
            [
                {
                    "op": "set_line",
                    "anchor": _anchor(2, "bbb"),
                    "content": raw_content,
                }
            ]
        )
        result = hashline_edit(path="f.txt", edits=edits, auto_cleanup=False)
        assert "Applied 1 edit" in result
        assert f.read_text() == f"aaa\n{raw_content}\nccc\n"


class TestHashlineEditAtomicWrite:
    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX permissions not supported on Windows"
    )
    def test_preserves_permissions(self, tools, tmp_path):
        """Atomic write preserves original file permissions."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\n")
        os.chmod(f, 0o755)

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        hashline_edit(path="f.txt", edits=edits)
        assert os.stat(f).st_mode & 0o777 == 0o755

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only ACL test")
    def test_acl_preserved_after_edit_windows(self, tools, tmp_path):
        """Atomic replace preserves the target file's DACL on Windows."""
        import ctypes

        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        SE_FILE_OBJECT = 1
        DACL_SECURITY_INFORMATION = 0x00000004

        advapi32.GetNamedSecurityInfoW.argtypes = [
            ctypes.wintypes.LPCWSTR,  # pObjectName
            ctypes.c_uint,  # ObjectType (SE_OBJECT_TYPE enum)
            ctypes.wintypes.DWORD,  # SecurityInfo
            ctypes.c_void_p,  # ppsidOwner
            ctypes.c_void_p,  # ppsidGroup
            ctypes.c_void_p,  # ppDacl
            ctypes.c_void_p,  # ppSacl
            ctypes.c_void_p,  # ppSecurityDescriptor
        ]
        advapi32.GetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD

        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p,  # SecurityDescriptor
            ctypes.wintypes.DWORD,  # RequestedStringSDRevision
            ctypes.wintypes.DWORD,  # SecurityInformation
            ctypes.c_void_p,  # StringSecurityDescriptor (out)
            ctypes.c_void_p,  # StringSecurityDescriptorLen (out, optional)
        ]
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = ctypes.wintypes.BOOL

        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\n")

        def _read_dacl_sddl(path):
            sd = ctypes.c_void_p()
            dacl = ctypes.c_void_p()
            rc = advapi32.GetNamedSecurityInfoW(
                str(path),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(dacl),
                None,
                ctypes.byref(sd),
            )
            assert rc == 0, f"GetNamedSecurityInfoW failed: {rc}"
            sddl = ctypes.c_wchar_p()
            assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd,
                1,
                DACL_SECURITY_INFORMATION,
                ctypes.byref(sddl),
                None,
            )
            value = sddl.value
            kernel32.LocalFree(sddl)
            kernel32.LocalFree(sd)
            return value

        acl_before = _read_dacl_sddl(f)

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        hashline_edit(path="f.txt", edits=edits)

        acl_after = _read_dacl_sddl(f)

        assert acl_before == acl_after, f"ACL changed after edit: {acl_before} -> {acl_after}"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only ACL test")
    def test_edit_succeeds_when_dacl_unavailable_windows(self, tools, tmp_path):
        """Edit still works on volumes without ACL support (e.g. FAT32)."""
        from aden_tools import _win32_atomic

        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\n")

        with patch.object(_win32_atomic, "snapshot_dacl", return_value=None):
            edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
            hashline_edit(path="f.txt", edits=edits)

        assert f.read_text().splitlines()[0].endswith("AAA")

    def test_preserves_trailing_newline(self, tools, tmp_path):
        """Files with trailing newline keep it after edit."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        hashline_edit(path="f.txt", edits=edits)
        assert f.read_text().endswith("\n")

    def test_unknown_op(self, tools, tmp_path):
        """Unknown op returns error."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\n")

        edits = json.dumps([{"op": "delete_line", "anchor": "1:abcd"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Error" in result
        assert "unknown op" in result

    def test_crlf_replace_op_no_double_conversion(self, tools, tmp_path):
        """Replace op on a CRLF file should not corrupt \\r\\n in new_content."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_bytes(b"aaa\r\nbbb\r\nccc\r\n")

        edits = json.dumps([{"op": "replace", "old_content": "aaa", "new_content": "x\r\ny"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Error" not in result

        raw = f.read_bytes()
        assert b"\r\r\n" not in raw
        assert raw == b"x\r\ny\r\nbbb\r\nccc\r\n"


class TestHashlineEditResponseFormat:
    def test_shows_updated_content(self, tools, tmp_path):
        """Response includes updated hashline content."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        result = hashline_edit(path="f.txt", edits=edits)
        # Should show updated content in hashline format
        h_new = compute_line_hash("BBB")
        assert f"2:{h_new}|BBB" in result

    def test_pagination_hint_for_large_files(self, tools, tmp_path):
        """Response includes pagination hint when file > 200 lines."""
        hashline_edit = tools[0]["hashline_edit"]
        f = tmp_path / "f.txt"
        lines = [f"line{i}" for i in range(300)]
        f.write_text("\n".join(lines) + "\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "line0"), "content": "FIRST"}])
        result = hashline_edit(path="f.txt", edits=edits)
        assert "Showing first 200" in result
        assert "300 lines" in result
