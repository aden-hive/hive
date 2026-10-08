"""Browser profile discovery: the always-on browser tools must surface ALL
connected Chrome profiles so an agent can see/target each one — not just the
single profile of its own context.

The bridge accessor is sync in host mode but a coroutine via the client-mode
RemoteBridge RPC, so the lifecycle helper must await it conditionally and never
raise.
"""

from __future__ import annotations

import pytest

import gcu.browser.tools.lifecycle as lc
from gcu.browser.bridge import BeelineBridge, _Connection
from gcu.browser.bridge_rpc import RPC_METHODS


def test_connected_profiles_is_rpc_reachable_for_workers():
    # Client-mode (worker) gcu tools call the bridge over RPC; the accessor must
    # be allowlisted or RemoteBridge.__getattr__ refuses it.
    assert "connected_profiles" in RPC_METHODS


def test_bridge_connected_profiles_lists_every_connection():
    bridge = BeelineBridge()

    class _WS:
        async def send(self, d):
            pass

        async def close(self, *a, **k):
            pass

    for lbl in ("silent-lime-narwhal", "fancy-emerald-wolf"):
        c = _Connection(_WS(), label=lbl)
        c.protocol_version = 5
        bridge._conns[lbl] = c
    bridge._starred_default_label = "fancy-emerald-wolf"

    profs = bridge.connected_profiles()
    assert {p["label"] for p in profs} == {"silent-lime-narwhal", "fancy-emerald-wolf"}
    by = {p["label"]: p for p in profs}
    assert by["fancy-emerald-wolf"]["starred"] is True
    assert by["fancy-emerald-wolf"]["is_default"] is True
    assert by["silent-lime-narwhal"]["is_default"] is False


@pytest.mark.asyncio
async def test_connected_profiles_helper_awaits_conditionally_and_is_safe():
    # Host-mode bridge: sync method.
    class SyncBridge:
        def connected_profiles(self):
            return [{"label": "a"}, {"label": "b"}]

    got = await lc._connected_profiles(SyncBridge())
    assert {p["label"] for p in got} == {"a", "b"}

    # Client-mode (RemoteBridge): the forwarder is a coroutine.
    class AsyncBridge:
        async def connected_profiles(self):
            return [{"label": "x"}]

    got = await lc._connected_profiles(AsyncBridge())
    assert got == [{"label": "x"}]

    # Older bridge without the accessor → [], never raises.
    class NoMethod:
        pass

    assert await lc._connected_profiles(NoMethod()) == []

    # Any error → [], never raises (so discovery never breaks a tool call).
    class Raises:
        def connected_profiles(self):
            raise RuntimeError("boom")

    assert await lc._connected_profiles(Raises()) == []
