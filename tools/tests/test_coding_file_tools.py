"""Structured editing as exposed to coding roles, with real freshness guards."""

import pytest

from aden_tools.file_ops import register_file_tools
from aden_tools.file_state_cache import reset_all


@pytest.fixture
def coding_tools(mcp):
    reset_all()
    register_file_tools(mcp, tool_names={"read_file", "edit_file"})
    tools = {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}
    assert set(tools) == {"read_file", "edit_file"}
    yield tools
    reset_all()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("mode", ["replace", "patch"])
def test_edits_preserve_unrelated_bytes_and_line_endings(coding_tools, tmp_path, newline, mode):
    target = tmp_path / "code.py"
    original = newline.join([b"# keep", b"value = 1", b"# keep too", b""])
    target.write_bytes(original)
    context = {"session_cwd": str(tmp_path)}
    coding_tools["read_file"](path="code.py", **context)
    if mode == "replace":
        result = coding_tools["edit_file"](path="code.py", old_string="value = 1", new_string="value = 2\nextra = 3", **context)
    else:
        result = coding_tools["edit_file"](
            mode="patch", patch_text="*** Begin Patch\n*** Update File: code.py\n-value = 1\n+value = 2\n+extra = 3\n*** End Patch\n", **context
        )
    assert "Error" not in result and "Refusing" not in result, result
    assert "code.py" in result
    assert target.read_bytes() == original.replace(b"value = 1", newline.join([b"value = 2", b"extra = 3"]))


def test_ambiguous_replacement_leaves_file_untouched(coding_tools, tmp_path):
    target = tmp_path / "code.py"
    original = b"value = 1\nvalue = 1\n"
    target.write_bytes(original)
    coding_tools["read_file"](path="code.py", session_cwd=str(tmp_path))
    result = coding_tools["edit_file"](path="code.py", old_string="value = 1", new_string="value = 2", session_cwd=str(tmp_path))
    assert "unique match" in result
    assert target.read_bytes() == original


def test_bad_patch_does_not_commit_earlier_operation(coding_tools, tmp_path):
    target = tmp_path / "code.py"
    target.write_bytes(b"value = 1\n")
    result = coding_tools["edit_file"](
        mode="patch",
        patch_text="*** Begin Patch\n*** Update File: code.py\n-value = 1\n+value = 2\n*** Update File: missing.py\n-x\n+y\n*** End Patch\n",
        session_cwd=str(tmp_path),
    )
    assert "no files were modified" in result
    assert target.read_bytes() == b"value = 1\n"


def test_shared_server_uses_each_sessions_workdir(coding_tools, tmp_path):
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        (root / "code.py").write_text(f"value = '{name}'\n")
        context = {"session_cwd": str(root)}
        assert name in coding_tools["read_file"](path="code.py", **context)
        result = coding_tools["edit_file"](path="code.py", old_string=name, new_string=name.upper(), **context)
        assert "Replaced" in result
        assert name.upper() in (root / "code.py").read_text()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_patch_accepts_bare_and_hint_headers(coding_tools, tmp_path, newline):
    target = tmp_path / "code.py"
    target.write_bytes(newline.join([b"first = 1", b"# preserve", b"second = 2", b""]))
    result = coding_tools["edit_file"](
        mode="patch",
        patch_text="*** Update File: code.py\n@@\n-first = 1\n+first = 10\n@@ second @@\n-second = 2\n+second = 20\n",
        session_cwd=str(tmp_path),
    )
    assert "Error" not in result, result
    assert target.read_bytes() == newline.join([b"first = 10", b"# preserve", b"second = 20", b""])


@pytest.mark.parametrize("bad_hunk", ["@@ missing closer\n-x\n+y", "@@", ""])
def test_invalid_hunk_reports_example_and_prevents_all_writes(coding_tools, tmp_path, bad_hunk):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    original = b"value = 1\n"
    first.write_bytes(original)
    second.write_bytes(original)
    result = coding_tools["edit_file"](
        mode="patch",
        patch_text=f"*** Update File: first.py\n@@\n-value = 1\n+value = 2\n*** Update File: second.py\n{bad_hunk}\n*** End Patch",
        session_cwd=str(tmp_path),
    )
    assert "Example:\n@@\n-old text\n+new text" in result
    assert "second.py" in result
    assert first.read_bytes() == second.read_bytes() == original


def test_malformed_second_header_rejects_same_file_patch(coding_tools, tmp_path):
    target = tmp_path / "code.py"
    target.write_bytes(b"value = 1\n")
    result = coding_tools["edit_file"](
        mode="patch",
        patch_text="*** Update File: code.py\n@@\n-value = 1\n+value = 2\n@@ invalid header\n-x\n+y\n",
        session_cwd=str(tmp_path),
    )
    assert "invalid hunk header" in result
    assert target.read_bytes() == b"value = 1\n"
