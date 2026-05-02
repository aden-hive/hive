"""Job lifecycle: ring buffer offsets, signals, stdin."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def job_tools(mcp):
    from terminal_tools.jobs.tools import register_job_tools

    register_job_tools(mcp)
    return {
        "start": mcp._tool_manager._tools["terminal_job_start"].fn,
        "logs": mcp._tool_manager._tools["terminal_job_logs"].fn,
        "manage": mcp._tool_manager._tools["terminal_job_manage"].fn,
    }


def test_start_logs_wait_basic(job_tools):
    started = job_tools["start"](command="echo first; echo second; echo third", shell=True)
    assert "job_id" in started
    job_id = started["job_id"]

    # Wait for completion via logs
    result = job_tools["logs"](job_id=job_id, wait_until_exit=True, wait_timeout_sec=5)
    assert result["status"] == "exited"
    assert result["exit_code"] == 0
    assert "first" in result["data"] and "third" in result["data"]


def test_offset_bookkeeping(job_tools):
    started = job_tools["start"](
        command="for i in 1 2 3 4 5; do echo line$i; sleep 0.1; done",
        shell=True,
    )
    job_id = started["job_id"]

    # Read a couple times with offset bookkeeping
    seen = ""
    offset = 0
    for _ in range(20):
        result = job_tools["logs"](job_id=job_id, since_offset=offset, max_bytes=4096)
        seen += result["data"]
        offset = result["next_offset"]
        if result["status"] == "exited":
            # Drain anything left
            tail = job_tools["logs"](job_id=job_id, since_offset=offset, max_bytes=4096)
            seen += tail["data"]
            break
        time.sleep(0.1)

    for n in range(1, 6):
        assert f"line{n}" in seen, f"missing line{n} from {seen!r}"


def test_merge_stderr(job_tools):
    started = job_tools["start"](
        command="echo stdout1; echo stderr1 1>&2; echo stdout2",
        shell=True,
        merge_stderr=True,
    )
    job_id = started["job_id"]
    result = job_tools["logs"](job_id=job_id, stream="merged", wait_until_exit=True, wait_timeout_sec=5)
    assert "stdout1" in result["data"]
    assert "stderr1" in result["data"]


def test_signal_term(job_tools):
    started = job_tools["start"](command="sleep 30")
    job_id = started["job_id"]

    # Give it a moment to actually start
    time.sleep(0.2)

    result = job_tools["manage"](action="signal_term", job_id=job_id)
    assert result["ok"] is True

    final = job_tools["logs"](job_id=job_id, wait_until_exit=True, wait_timeout_sec=3)
    assert final["status"] == "exited"
    # On SIGTERM, exit_code is -15 (subprocess convention)
    assert final["exit_code"] == -15


def test_list_action(job_tools):
    started = job_tools["start"](command="sleep 1")
    listing = job_tools["manage"](action="list")
    assert any(j["job_id"] == started["job_id"] for j in listing["jobs"])


def test_unknown_job_id(job_tools):
    result = job_tools["logs"](job_id="job_doesnotexist", wait_until_exit=False)
    assert "error" in result
