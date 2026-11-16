"""Tests can't reach a real Hive home through paths computed at import."""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pytest

# Paths Hive modules compute from HIVE_HOME when imported, which the per-test
# sandbox does not repoint. One of them, the credential key, was overwritten in
# a real home by a test run.
_IMPORT_TIME_PATHS = [
    ("framework.credentials.key_storage", "CREDENTIAL_KEY_PATH"),
    ("framework.sentinel.token", "_SECRET_PATH"),
    ("framework.sentinel.runtime_identity", "_ID_PATH"),
    ("framework.server.routes_prompts", "CUSTOM_PROMPTS_FILE"),
    ("framework.storage.migrate_v3", "_MIGRATION_MARKER"),
]


@pytest.mark.parametrize(("module", "name"), _IMPORT_TIME_PATHS)
def test_import_time_paths_are_in_a_temporary_directory(module, name):
    path = Path(getattr(importlib.import_module(module), name)).resolve()

    assert path.is_relative_to(Path(tempfile.gettempdir()).resolve())


def test_a_fake_credential_key_does_not_outlive_its_test(tmp_path, monkeypatch):
    from framework.credentials import key_storage

    key_path = tmp_path / "credential_key"
    key_path.write_text("from-disk", encoding="utf-8")
    monkeypatch.setattr(key_storage, "CREDENTIAL_KEY_PATH", key_path)
    monkeypatch.delenv("HIVE_CREDENTIAL_KEY", raising=False)

    key_storage.load_credential_key()

    # load_credential_key() sets the variable itself; the autouse sandbox puts it back.
    assert os.environ["HIVE_CREDENTIAL_KEY"] == "from-disk"


def test_the_previous_tests_key_is_gone():
    assert os.environ.get("HIVE_CREDENTIAL_KEY") != "from-disk"
