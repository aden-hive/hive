"""A queen's pending requests to add a skill to the shared library (framework.skills.install_requests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.skills import install_requests
from framework.skills.skill_writer import build_draft


def _draft(name: str = "house-style", body: str = "# House style\n\nLead with the answer.\n"):
    draft, err = build_draft(skill_name=name, skill_description="How Ava formats her reports.", skill_body=body)
    assert draft is not None, err
    return draft


def test_a_new_request_replaces_the_pending_one_for_the_same_name(tmp_path: Path) -> None:
    first = install_requests.add_request(tmp_path, _draft())
    other = install_requests.add_request(tmp_path, _draft(name="other-skill"))
    second = install_requests.add_request(tmp_path, _draft(body="# House style\n\nShorter.\n"))

    assert [r["id"] for r in install_requests.pending_requests(tmp_path)] == [other["id"], second["id"]]
    assert first["id"] != second["id"]


def test_a_decided_request_is_no_longer_pending(tmp_path: Path) -> None:
    request = install_requests.add_request(tmp_path, _draft())

    install_requests.mark_decided(tmp_path, request["id"], "denied")

    assert install_requests.pending_requests(tmp_path) == []
    with pytest.raises(install_requests.RequestDecided, match="already denied"):
        install_requests.pending_request(tmp_path, request["id"])


def test_an_unknown_request_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(install_requests.RequestNotFound, match="no skill install request nope"):
        install_requests.pending_request(tmp_path, "nope")


def test_the_stored_copy_is_what_gets_installed(tmp_path: Path) -> None:
    request = install_requests.add_request(tmp_path, _draft())

    draft = install_requests.draft_of(install_requests.pending_request(tmp_path, request["id"]))

    assert (draft.name, draft.body) == ("house-style", "# House style\n\nLead with the answer.\n")
