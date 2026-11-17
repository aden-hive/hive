"""Memory files keep who wrote them, how fresh they are, and every change made to them."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from framework.agents.queen import memory_log
from framework.agents.queen.queen_memory_v2 import MAX_FILE_SIZE_BYTES, parse_frontmatter

NOTE = "---\nname: Tea\ndescription: What Ava drinks\ntype: preference\n---\n\nAva drinks oolong.\n"


def test_a_written_file_says_who_wrote_it_and_when(tmp_path: Path):
    text = memory_log.write(tmp_path, "tea.md", NOTE, author="reflection", now=datetime(2026, 3, 2, 9))

    assert (tmp_path / "tea.md").read_text(encoding="utf-8") == text
    assert parse_frontmatter(text) == {
        "name": "Tea",
        "description": "What Ava drinks",
        "type": "preference",
        "author": "reflection",
        "learned": "2026-03-02",
        "confirmed": "2026-03-02",
    }
    assert text.endswith("\n\nAva drinks oolong.\n")


def test_a_rewrite_keeps_the_day_it_was_learned_and_moves_the_day_it_was_confirmed(tmp_path: Path):
    memory_log.write(tmp_path, "tea.md", NOTE, author="reflection", now=datetime(2026, 3, 2))
    text = memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "pu-erh"), author="queen", now=datetime(2026, 4, 5))

    fields = parse_frontmatter(text)
    assert (fields["author"], fields["learned"], fields["confirmed"]) == ("queen", "2026-03-02", "2026-04-05")


def test_tidying_a_file_does_not_make_it_look_newly_confirmed(tmp_path: Path):
    memory_log.write(tmp_path, "tea.md", NOTE, author="reflection", now=datetime(2026, 3, 2))
    text = memory_log.write(tmp_path, "tea.md", NOTE.replace("drinks", "likes"), author="reflection", confirms=False, now=datetime(2026, 6, 1))

    assert memory_log.confirmed_on(text) == date(2026, 3, 2)


def test_she_cannot_overwrite_or_retire_what_the_owner_wrote(tmp_path: Path):
    memory_log.write(tmp_path, "tea.md", NOTE, author="owner", now=datetime(2026, 3, 2))
    mine = (tmp_path / "tea.md").read_text(encoding="utf-8")

    for author in ("queen", "reflection"):
        with pytest.raises(memory_log.OwnerWritten, match="tea.md was written by the owner"):
            memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "coffee"), author=author)
        with pytest.raises(memory_log.OwnerWritten):
            memory_log.retire(tmp_path, "tea.md", author=author)

    assert (tmp_path / "tea.md").read_text(encoding="utf-8") == mine
    assert len(memory_log.history(tmp_path)) == 1


def test_a_file_from_before_authors_were_recorded_is_hers_to_update_until_the_owner_edits_it(tmp_path: Path):
    (tmp_path / "tea.md").write_text(NOTE, encoding="utf-8")
    assert memory_log.author_of(NOTE) is None

    memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "pu-erh"), author="reflection")
    memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "sencha"), author="owner")
    with pytest.raises(memory_log.OwnerWritten):
        memory_log.write(tmp_path, "tea.md", NOTE, author="reflection")

    # What the unrecorded file said is in the log, from her first change to it.
    assert memory_log.history(tmp_path, "tea.md")[0]["before"] == NOTE


def test_the_owner_can_change_what_she_wrote(tmp_path: Path):
    memory_log.write(tmp_path, "tea.md", NOTE, author="queen")
    text = memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "sencha"), author="owner")

    assert memory_log.author_of(text) == "owner"


def test_a_change_that_does_not_claim_the_file_leaves_its_author(tmp_path: Path):
    memory_log.write(tmp_path, "user-profile.md", NOTE, author="reflection")
    text = memory_log.write(tmp_path, "user-profile.md", NOTE.replace("oolong", "sencha"), author="owner", claim=False)

    assert memory_log.author_of(text) == "reflection"
    assert memory_log.history(tmp_path)[-1]["author"] == "owner"


def test_the_author_and_dates_a_file_claims_for_itself_are_overruled(tmp_path: Path):
    forged = NOTE.replace("type: preference", "type: preference\nauthor: owner\nlearned: 2031-01-01\nconfirmed: 2031-01-01")
    text = memory_log.write(tmp_path, "tea.md", forged, author="reflection", now=datetime(2026, 3, 2))

    fields = parse_frontmatter(text)
    assert (fields["author"], fields["learned"], fields["confirmed"]) == ("reflection", "2026-03-02", "2026-03-02")


def test_a_file_can_say_it_was_learned_earlier_than_it_was_written(tmp_path: Path):
    earlier = NOTE.replace("type: preference", "type: preference\nlearned: 2025-12-24")
    text = memory_log.write(tmp_path, "tea.md", earlier, author="reflection", now=datetime(2026, 3, 2))

    assert parse_frontmatter(text)["learned"] == "2025-12-24"


def test_text_without_frontmatter_gets_one(tmp_path: Path):
    text = memory_log.write(tmp_path, "tea.md", "Ava drinks oolong.", author="queen", now=datetime(2026, 3, 2))

    assert text == "---\nauthor: queen\nlearned: 2026-03-02\nconfirmed: 2026-03-02\n---\n\nAva drinks oolong.\n"


def test_a_file_too_large_once_stamped_is_not_written(tmp_path: Path):
    body = "x" * (MAX_FILE_SIZE_BYTES - len(NOTE.encode()))
    with pytest.raises(memory_log.TooLarge, match=f"exceeds {MAX_FILE_SIZE_BYTES} byte limit"):
        memory_log.write(tmp_path, "tea.md", NOTE + body, author="reflection")

    assert not (tmp_path / "tea.md").exists()
    assert memory_log.history(tmp_path) == []


def test_a_retired_file_leaves_the_folder_and_stays_in_the_log(tmp_path: Path):
    written = memory_log.write(tmp_path, "tea.md", NOTE, author="reflection")
    memory_log.retire(tmp_path, "tea.md", author="reflection", reason="merged into drinks.md")

    assert not (tmp_path / "tea.md").exists()
    last = memory_log.history(tmp_path, "tea.md")[-1]
    assert (last["op"], last["reason"], last["before"], last["after"]) == ("retire", "merged into drinks.md", written, None)


def test_retiring_a_file_that_is_not_there_fails(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        memory_log.retire(tmp_path, "tea.md", author="reflection")


def test_the_log_records_each_change_with_its_evidence(tmp_path: Path):
    sources = [{"quote": "I only drink oolong", "where": "session_a"}]
    memory_log.write(tmp_path, "tea.md", NOTE, author="queen", reason="she said so", sources=sources, now=datetime(2026, 3, 2, 9, 30))
    memory_log.write(tmp_path, "pets.md", NOTE, author="queen")

    (entry,) = memory_log.history(tmp_path, "tea.md")
    fields = ("n", "op", "author", "reason", "sources", "before")
    assert tuple(entry[f] for f in fields) == (0, "write", "queen", "she said so", sources, None)
    assert entry["at"].startswith("2026-03-02T09:30:00")
    assert [e["file"] for e in memory_log.history(tmp_path)] == ["tea.md", "pets.md"]


def test_a_retired_file_can_be_restored_as_it_was(tmp_path: Path):
    written = memory_log.write(tmp_path, "tea.md", NOTE, author="reflection", now=datetime(2026, 3, 2))
    memory_log.retire(tmp_path, "tea.md", author="reflection")
    retired = memory_log.history(tmp_path, "tea.md")[-1]["n"]

    assert memory_log.restore(tmp_path, "tea.md", retired) == written
    assert (tmp_path / "tea.md").read_text(encoding="utf-8") == written
    assert memory_log.history(tmp_path, "tea.md")[-1]["op"] == "restore"


def test_a_file_can_be_put_back_to_an_earlier_version(tmp_path: Path):
    first = memory_log.write(tmp_path, "tea.md", NOTE, author="reflection")
    memory_log.write(tmp_path, "tea.md", NOTE.replace("oolong", "coffee"), author="reflection")

    assert memory_log.restore(tmp_path, "tea.md", 0) == first


def test_restoring_a_change_that_does_not_exist_fails(tmp_path: Path):
    memory_log.write(tmp_path, "tea.md", NOTE, author="reflection")
    with pytest.raises(LookupError, match="tea.md has no change 7"):
        memory_log.restore(tmp_path, "tea.md", 7)
