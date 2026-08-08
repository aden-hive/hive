"""Unit tests for framework.utils.tool_suggestions."""

from framework.utils.tool_suggestions import format_unknown_tool_error


def test_no_close_match_returns_bare_message():
    """Names with no close match yield the bare Unknown tool message."""
    known = ["web_search", "exa_search"]
    assert format_unknown_tool_error("fetch_news", known) == "Unknown tool: fetch_news"


def test_close_typo_suggests_best_matches():
    """A typo should produce a Did you mean hint with the closest names."""
    known = ["web_search", "exa_search"]
    message = format_unknown_tool_error("web_seach", known)
    assert message.startswith("Unknown tool: web_seach")
    assert "Did you mean: web_search, exa_search?" in message


def test_suggestions_capped_at_two():
    """Suggestion lists never exceed the cap, even with many candidates."""
    known = [
        "list_memory_files",
        "read_memory_file",
        "write_memory_file",
        "delete_memory_file",
        "format_memory_manifest",
    ]
    message = format_unknown_tool_error("read_memry_fil", known)
    suggestions = message.split("Did you mean: ", 1)[1].rstrip("?")
    assert len(suggestions.split(", ")) <= 2
    assert "read_memory_file" in suggestions
