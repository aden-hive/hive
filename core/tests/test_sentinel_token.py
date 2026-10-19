"""Tests for Sentinel correlation tokens (framework.sentinel.token)."""

from __future__ import annotations

import pytest

from framework.sentinel import token


@pytest.fixture(autouse=True)
def _fixed_secret(monkeypatch):
    # Deterministic secret so tokens are stable and no file I/O happens.
    monkeypatch.setattr(token, "_cached_secret", b"0" * 32)
    yield


def test_token_round_trips() -> None:
    tok = token.make_token("esc_abc123")
    assert token.verify_token(tok, "esc_abc123")


def test_token_is_deterministic() -> None:
    assert token.make_token("esc_x") == token.make_token("esc_x")


def test_token_differs_per_escalation() -> None:
    assert token.make_token("esc_a") != token.make_token("esc_b")


def test_verify_rejects_wrong_id() -> None:
    tok = token.make_token("esc_a")
    assert not token.verify_token(tok, "esc_b")


def test_verify_rejects_tampered_token() -> None:
    tok = token.make_token("esc_a")
    tampered = ("x" if tok[0] != "x" else "y") + tok[1:]
    assert not token.verify_token(tampered, "esc_a")


def test_verify_rejects_empty() -> None:
    assert not token.verify_token("", "esc_a")
    assert not token.verify_token(None, "esc_a")


def test_extract_token_from_reply() -> None:
    tok = token.make_token("esc_a")
    reply = f"Yes go ahead {token.format_ref(tok)}"
    assert token.extract_token(reply) == tok


def test_extract_token_missing() -> None:
    assert token.extract_token("just a normal reply") is None
    assert token.extract_token("") is None


def test_strip_ref_removes_footer() -> None:
    tok = token.make_token("esc_a")
    reply = f"Continue please {token.format_ref(tok)}"
    stripped = token.strip_ref(reply)
    assert "ref:" not in stripped
    assert stripped == "Continue please"
