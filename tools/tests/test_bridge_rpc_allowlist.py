"""Every bridge method the browser tools and CLI call must be RPC-forwardable.

The CLI talks to bridge_host through ``RemoteBridge``, which forwards only
names in ``RPC_METHODS``. ``screenshot_region`` (``interact --action zoom``)
was missing, so zoom always failed with the bare error "screenshot_region".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gcu.browser.bridge import BeelineBridge
from gcu.browser.bridge_rpc import RPC_METHODS, RemoteBridge

_GCU = Path(__file__).resolve().parents[1] / "src" / "gcu"
# Host-mode lifecycle, never forwarded: RemoteBridge has its own connect/stop.
_LOCAL_LIFECYCLE = {"start", "stop", "connect"}


def _bridge_calls() -> set[str]:
    sources = [*(_GCU / "browser" / "tools").glob("*.py"), *(_GCU / "cli_commands").glob("*.py")]
    pattern = re.compile(r"\bbridge\.([a-z_][a-z0-9_]*)\(")
    return {m.group(1) for f in sources for m in pattern.finditer(f.read_text(encoding="utf-8"))}


def test_every_called_bridge_method_is_forwardable():
    called = {n for n in _bridge_calls() if hasattr(BeelineBridge, n)} - _LOCAL_LIFECYCLE
    assert called - RPC_METHODS == set()


def test_unknown_method_error_names_the_problem():
    bridge = object.__new__(RemoteBridge)  # attribute lookup needs no live connection

    with pytest.raises(AttributeError, match="not a bridge RPC method"):
        bridge.definitely_not_a_method  # noqa: B018 - the lookup is the behaviour under test
