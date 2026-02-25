"""Shared fixtures for tools tests."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialStoreAdapter

logger = logging.getLogger(__name__)


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def mock_credentials() -> CredentialStoreAdapter:
    """Create a CredentialStoreAdapter with mock test credentials."""
    return CredentialStoreAdapter.for_testing(
        {
            "anthropic": "test-anthropic-api-key",
            "brave_search": "test-brave-api-key",
            # Add other mock credentials as needed
        }
    )


@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """Create a simple text file for testing."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello, World!\nLine 2\nLine 3")
    return txt_file


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a simple CSV file for testing."""
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,Chicago\n")
    return csv_file


@pytest.fixture
def sample_json(tmp_path: Path) -> Path:
    """Create a simple JSON file for testing."""
    json_file = tmp_path / "test.json"
    json_file.write_text('{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}')
    return json_file


@pytest.fixture
def large_text_file(tmp_path: Path) -> Path:
    """Create a large text file for size limit testing."""
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 20_000_000)  # 20MB
    return large_file


@pytest.fixture(scope="session")
def live_credential_resolver() -> Callable[[str], str | None]:
    """Resolve live credentials for integration tests.

    Tries two sources in order:
    1. Environment variable (spec.env_var)
    2. CredentialStoreAdapter.default() (encrypted store + env fallback)

    Returns a callable: resolver(credential_name) -> str | None.
    Credential values are never logged or exposed in test output.
    """
    _adapter: CredentialStoreAdapter | None = None
    _adapter_init_failed = False

    def _get_adapter() -> CredentialStoreAdapter | None:
        nonlocal _adapter, _adapter_init_failed
        if _adapter is not None:
            return _adapter
        if _adapter_init_failed:
            return None
        try:
            _adapter = CredentialStoreAdapter.default()
        except Exception as exc:
            logger.debug("Could not initialize CredentialStoreAdapter: %s", exc)
            _adapter_init_failed = True
        return _adapter

    def resolve(credential_name: str) -> str | None:
        spec = CREDENTIAL_SPECS.get(credential_name)
        if spec is None:
            return None

        # 1. Try env var directly
        value = os.environ.get(spec.env_var)
        if value:
            return value

        # 2. Try the adapter (encrypted store + fallback)
        adapter = _get_adapter()
        if adapter is not None:
            try:
                value = adapter.get(credential_name)
                if value:
                    return value
            except Exception:
                pass

        return None

    return resolve
