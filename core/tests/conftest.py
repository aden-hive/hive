"""Test setup for framework tests.

Ensures `framework.loader` submodules are bound as attributes on their
parent package so monkeypatch's dotted-string API
(`monkeypatch.setattr("framework.loader.foo.Y", ...)`) reliably resolves
the submodule even when no test has imported it yet.
"""

from __future__ import annotations

import framework.loader  # noqa: F401 — load parent package first
import framework.loader.mcp_client as _mcp_client
import framework.loader.mcp_connection_manager as _mcp_connection_manager
import framework.loader.mcp_registry as _mcp_registry

framework.loader.mcp_registry = _mcp_registry
framework.loader.mcp_connection_manager = _mcp_connection_manager
framework.loader.mcp_client = _mcp_client
