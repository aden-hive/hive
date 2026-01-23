"""Shared fixtures for tools tests."""
import pytest
from pathlib import Path

from fastmcp import FastMCP

from aden_tools.credentials import CredentialManager


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def mock_credentials() -> CredentialManager:
    """Create a CredentialManager with mock test credentials."""
    return CredentialManager.for_testing({
        "anthropic": "test-anthropic-api-key",
        "brave_search": "test-brave-api-key",
        # Add other mock credentials as needed
    })


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
