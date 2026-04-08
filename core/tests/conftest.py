"""Test setup for framework tests."""

from __future__ import annotations

# Ensure framework.runner submodules are bound as attributes on their parent
# package. Under this repo's layout, `from framework.runner.foo import X` does
# not always bind `foo` onto `framework.runner` (observed via dir() inspection),
# which breaks `monkeypatch.setattr("framework.runner.foo.Y", ...)` because the
# pytest path resolver walks attributes. Force the bindings here so tests can
# patch submodule attributes via the dotted-string API.
import framework.runner  # noqa: F401 — load parent package first
import framework.runner.mcp_client as _mcp_client
import framework.runner.mcp_connection_manager as _mcp_connection_manager
import framework.runner.mcp_registry as _mcp_registry

framework.runner.mcp_registry = _mcp_registry
framework.runner.mcp_connection_manager = _mcp_connection_manager
framework.runner.mcp_client = _mcp_client
