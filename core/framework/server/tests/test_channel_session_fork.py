"""A chat channel's session isn't forked away by task_create(new_session=true)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework.server.routes_execution import ForkSessionError, fork_queen_session_for_split

pytestmark = pytest.mark.asyncio


async def test_a_channel_thread_stays_in_its_session(tmp_path):
    queen_dir = tmp_path / "sess_group"
    queen_dir.mkdir()
    session = SimpleNamespace(id="sess_group", queen_dir=queen_dir, queen_name="queen_ava", channel="onebot")

    with pytest.raises(ForkSessionError, match="onebot chat channel and stays in this session") as caught:
        await fork_queen_session_for_split(
            session=session,
            manager=None,
            handoff="Check the evaluation numbers",
            tasks=[{"subject": "Check the evaluation numbers"}],
        )

    assert caught.value.status == 409
    assert not getattr(session, "superseded_by", None)
