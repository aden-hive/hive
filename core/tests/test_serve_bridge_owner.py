"""`hive serve` keeps the browser bridge alive whether or not the desktop launched it."""

import asyncio
import os

import pytest

from framework.loader import cli as runner_cli


@pytest.mark.parametrize(
    ("inherited", "expected"),
    [(None, "self"), ("4321", "4321"), ("not-a-pid", "self")],
)
def test_runtime_owner_is_the_desktop_or_this_process(monkeypatch, inherited, expected):
    if inherited is None:
        monkeypatch.delenv("HIVE_DESKTOP_PARENT_PID", raising=False)
    else:
        monkeypatch.setenv("HIVE_DESKTOP_PARENT_PID", inherited)
    want = os.getpid() if expected == "self" else int(expected)

    assert runner_cli._runtime_owner_pid() == want
    # Children (the bridge, gcu, the tool servers) inherit the same owner.
    assert os.environ["HIVE_DESKTOP_PARENT_PID"] == str(want)


class _FakeClient:
    calls: list[tuple] = []

    def __init__(self):
        self.is_connected = False

    def set_notify_handler(self, handler):
        pass

    async def connect(self):
        self.is_connected = True

    async def call(self, method, *args):
        _FakeClient.calls.append((method, *args))
        return {"ok": True}

    async def close(self):
        self.is_connected = False


@pytest.mark.asyncio
async def test_keepalive_starts_the_bridge_and_identifies_as_the_owner(monkeypatch):
    import gcu.bridge_host
    import gcu.browser.bridge_rpc

    ensured = []
    monkeypatch.setattr(gcu.bridge_host, "ensure_bridge_host_running", lambda: ensured.append(True) or True)
    monkeypatch.setattr(gcu.browser.bridge_rpc, "BridgeClient", _FakeClient)
    _FakeClient.calls = []

    task = asyncio.create_task(runner_cli._bridge_keepalive_loop(4321))
    for _ in range(100):
        if _FakeClient.calls:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert ensured == [True]
    assert _FakeClient.calls[0] == ("client_hello", 4321)
