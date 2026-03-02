from unittest.mock import patch

import pytest

from aden_tools.tools.csv_tool.csv_tool import register_tools


class MockMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(f):
            self.tools[f.__name__] = f
            return f

        return decorator


@pytest.fixture
def csv_tools():
    mcp = MockMCP()
    register_tools(mcp)
    return mcp.tools


def test_csv_read_oom_limit(csv_tools, tmp_path):
    csv_file = tmp_path / "large.csv"
    csv_file.write_text("col1,col2\n1,2")

    # Mock getsize to return > 10MB
    with patch("os.path.getsize", return_value=11 * 1024 * 1024):
        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_tools["csv_read"](
                path="large.csv", workspace_id="w", agent_id="a", session_id="s"
            )

    assert "error" in result
    assert "File too large" in result["error"]


def test_csv_sql_oom_limit(csv_tools, tmp_path):
    csv_file = tmp_path / "large.csv"
    csv_file.write_text("col1,col2\n1,2")

    # Mock getsize to return > 10MB
    with patch("os.path.getsize", return_value=11 * 1024 * 1024):
        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_tools["csv_sql"](
                path="large.csv",
                workspace_id="w",
                agent_id="a",
                session_id="s",
                query="SELECT * FROM data",
            )

    assert "error" in result
    assert "File too large" in result["error"]
