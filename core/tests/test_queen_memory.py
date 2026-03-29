from datetime import date

from framework.agents.queen import queen_memory
from framework.tools.queen_memory_tools import recall_diary


def test_format_memory_date_uses_unpadded_day() -> None:
    assert queen_memory.format_memory_date(date(2026, 3, 7)) == "March 7, 2026"


def test_format_for_injection_formats_recent_memory(monkeypatch) -> None:
    monkeypatch.setattr(queen_memory, "read_semantic_memory", lambda: "")
    monkeypatch.setattr(
        queen_memory,
        "_find_recent_episodic",
        lambda lookback=7: (date(2026, 3, 7), "Remembered context."),
    )

    result = queen_memory.format_for_injection()

    assert "## March 7, 2026" in result
    assert "Remembered context." in result


def test_recall_diary_formats_today_without_platform_specific_strftime(monkeypatch) -> None:
    monkeypatch.setattr(
        queen_memory,
        "read_episodic_memory",
        lambda d=None: "Today's note." if d == date.today() else "",
    )

    result = recall_diary(days_back=1)

    assert "## Today" in result
    assert "Today's note." in result
