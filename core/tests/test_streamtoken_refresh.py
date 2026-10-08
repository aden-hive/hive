"""
Tests for ``framework.server.streamtoken_refresh`` — the in-VM
background job that re-mints the runtime's own ``hive`` streamToken
before the 24h TTL expires.

The matrix:
  - ``decode_jwt_exp`` correctly extracts the unix timestamp from a
    valid token, returns ``None`` on garbage.
  - ``compute_sleep_seconds`` math: bounded by min/max, fires now
    when token is within threshold, sleeps to (exp - threshold - now)
    otherwise.
  - ``post_refresh`` happy-path returns the new token, error paths
    return ``None``.
  - ``try_refresh_now`` end-to-end: reads current token, posts to
    backend, saves the new token back to the credential store.
  - ``try_refresh_now`` no-ops when refresh isn't configured (module
    refs unset).
  - ``try_refresh_now`` returns ``None`` on backend failure without
    overwriting the existing credential.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

from framework.credentials.models import CredentialKey, CredentialObject
from framework.server import streamtoken_refresh as sr


def _make_jwt(payload: dict[str, Any]) -> str:
    """Build a valid-shape JWT (header.payload.signature) without
    actually signing anything. We only test the unsigned-decode path."""
    header = {"alg": "HS256", "typ": "JWT"}

    def b64(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode("utf-8")).rstrip(b"=").decode("ascii")

    return f"{b64(header)}.{b64(payload)}.fake-signature"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestDecodeJwtExp:
    def test_returns_exp_from_valid_token(self):
        token = _make_jwt({"sub": "u@e.com", "exp": 1_900_000_000})
        assert sr.decode_jwt_exp(token) == 1_900_000_000

    def test_returns_none_on_malformed_token(self):
        assert sr.decode_jwt_exp("not.a.jwt") is None
        assert sr.decode_jwt_exp("totally bogus") is None
        assert sr.decode_jwt_exp("") is None

    def test_returns_none_when_exp_missing(self):
        token = _make_jwt({"sub": "u@e.com"})  # no exp claim
        assert sr.decode_jwt_exp(token) is None


class TestComputeSleepSeconds:
    def test_exp_none_sleeps_min(self):
        # Unparseable token → re-check soon to recover from a
        # transient bad-credential state.
        assert sr.compute_sleep_seconds(None, now_unix=1000.0) == sr.MIN_SLEEP_SECONDS

    def test_within_threshold_fires_immediately(self):
        # exp 1h from now, threshold 2h → fire now (clamped to min).
        now = 1000.0
        exp = int(now + 3600)
        assert sr.compute_sleep_seconds(exp, now, refresh_before_seconds=7200) == sr.MIN_SLEEP_SECONDS

    def test_far_from_expiry_clamps_to_max(self):
        # exp 10h from now, threshold 2h → 8h until refresh, but
        # max_sleep caps that at 1h to keep re-checking periodically.
        now = 1000.0
        exp = int(now + 10 * 3600)
        out = sr.compute_sleep_seconds(exp, now, refresh_before_seconds=7200)
        assert out == sr.MAX_SLEEP_SECONDS

    def test_mid_range_returns_exact_gap(self):
        # exp 3000s from now, threshold 500s → 2500s until refresh.
        # That's within [60, 3600] so we get exactly 2500.
        now = 1000.0
        exp = int(now + 3000)
        out = sr.compute_sleep_seconds(
            exp,
            now,
            refresh_before_seconds=500,
            min_sleep=60,
            max_sleep=3600,
        )
        assert out == 2500


# ---------------------------------------------------------------------------
# post_refresh
# ---------------------------------------------------------------------------


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in. Returns a pre-canned response."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url: str, json: dict[str, Any] | None = None) -> httpx.Response:
        self.calls.append((url, json or {}))
        return self._response


def _resp(status: int, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {})


class TestPostRefresh:
    @pytest.mark.asyncio
    async def test_happy_path_returns_new_token(self):
        client = _FakeAsyncClient(_resp(200, {"success": True, "streamToken": "new-token-xyz"}))

        result = await sr.post_refresh(
            "https://app.example.com",
            "old-token",
            client_factory=lambda: client,
        )

        assert result == "new-token-xyz"
        # POST went to the right URL with the current token in the body.
        assert len(client.calls) == 1
        url, body = client.calls[0]
        assert url == "https://app.example.com/user/refresh-stream-token-from-stream"
        assert body == {"streamToken": "old-token"}

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self):
        client = _FakeAsyncClient(_resp(401, {"success": False, "msg": "expired"}))

        result = await sr.post_refresh(
            "https://app.example.com",
            "old-token",
            client_factory=lambda: client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_200_with_missing_streamToken_returns_none(self):
        # Backend somehow returns 200 but no streamToken in body — treat
        # as failure rather than overwriting the credential with "".
        client = _FakeAsyncClient(_resp(200, {"success": True}))

        result = await sr.post_refresh(
            "https://app.example.com",
            "old-token",
            client_factory=lambda: client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        class _Boom:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                raise httpx.ConnectError("simulated DNS failure")

        result = await sr.post_refresh(
            "https://app.example.com",
            "old-token",
            client_factory=lambda: _Boom(),
        )
        assert result is None


# ---------------------------------------------------------------------------
# try_refresh_now
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal credential store for testing. Just holds one credential."""

    def __init__(self, initial: CredentialObject | None = None):
        self._cred = initial
        self.save_calls: list[CredentialObject] = []

    def get_credential(self, credential_id: str) -> CredentialObject | None:
        if self._cred and self._cred.id == credential_id:
            return self._cred
        return None

    def save_credential(self, cred: CredentialObject) -> None:
        self.save_calls.append(cred)
        self._cred = cred


def _hive_cred(token: str) -> CredentialObject:
    from pydantic import SecretStr

    return CredentialObject(
        id=sr.CREDENTIAL_ID,
        keys={sr.KEY_NAME: CredentialKey(name=sr.KEY_NAME, value=SecretStr(token))},
    )


class TestTryRefreshNow:
    def setup_method(self):
        # Reset module-level refs between tests.
        sr._credential_store_ref = None
        sr._aden_base_url_ref = None
        sr._refresh_now_lock = None

    @pytest.mark.asyncio
    async def test_no_op_when_module_refs_unset(self):
        # Before start_streamtoken_refresh has run (or in standalone
        # tests), refresh isn't configured — try_refresh_now must
        # return None without erroring.
        result = await sr.try_refresh_now()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_op_when_credential_missing(self):
        sr._credential_store_ref = _FakeStore(initial=None)
        sr._aden_base_url_ref = "https://app.example.com"

        result = await sr.try_refresh_now()
        assert result is None

    @pytest.mark.asyncio
    async def test_happy_path_writes_new_token_to_store(self, monkeypatch):
        store = _FakeStore(initial=_hive_cred("old-token"))
        sr._credential_store_ref = store
        sr._aden_base_url_ref = "https://app.example.com"

        async def fake_post(base_url, current, *, client_factory=None):
            assert base_url == "https://app.example.com"
            assert current == "old-token"
            return "fresh-token-456"

        monkeypatch.setattr(sr, "post_refresh", fake_post)

        result = await sr.try_refresh_now()

        assert result == "fresh-token-456"
        assert len(store.save_calls) == 1
        saved = store.save_calls[0]
        assert saved.id == sr.CREDENTIAL_ID
        assert saved.get_key(sr.KEY_NAME) == "fresh-token-456"

    @pytest.mark.asyncio
    async def test_backend_failure_does_not_overwrite_existing_token(self, monkeypatch):
        store = _FakeStore(initial=_hive_cred("old-token"))
        sr._credential_store_ref = store
        sr._aden_base_url_ref = "https://app.example.com"

        async def fake_post_failing(base_url, current, *, client_factory=None):
            return None

        monkeypatch.setattr(sr, "post_refresh", fake_post_failing)

        result = await sr.try_refresh_now()

        assert result is None
        # The store should still hold the original token — a failed
        # refresh must not clobber the credential with an empty/None.
        assert len(store.save_calls) == 0
        assert store.get_credential(sr.CREDENTIAL_ID).get_key(sr.KEY_NAME) == "old-token"

    @pytest.mark.asyncio
    async def test_concurrent_callers_serialize_to_a_single_refresh(self, monkeypatch):
        # Three coroutines hit try_refresh_now simultaneously (LLM
        # call site retries from multiple queens at once). The lock
        # must ensure exactly one POST to the backend; the rest
        # observe the fresh credential left behind by the first
        # caller and skip their own refresh.
        import time

        # Stored token is expired — that's what triggered the call.
        old_token = _make_jwt({"sub": "u@e.com", "exp": int(time.time()) - 60})
        # New token the backend mints has exp comfortably past the
        # refresh threshold, so subsequent lock holders skip the POST.
        new_token = _make_jwt({"sub": "u@e.com", "exp": int(time.time()) + 24 * 3600})
        store = _FakeStore(initial=_hive_cred(old_token))
        sr._credential_store_ref = store
        sr._aden_base_url_ref = "https://app.example.com"

        post_count = 0

        async def fake_post(base_url, current, *, client_factory=None):
            nonlocal post_count
            post_count += 1
            # Yield to other coroutines so contention is exercised.
            await asyncio.sleep(0)
            return new_token

        monkeypatch.setattr(sr, "post_refresh", fake_post)

        results = await asyncio.gather(
            sr.try_refresh_now(),
            sr.try_refresh_now(),
            sr.try_refresh_now(),
        )

        # Without the lock guard + freshness re-check, post_count would
        # be 3. With them, exactly one HTTP call goes out and the rest
        # pick up the cached fresh token from the store on their re-read.
        assert post_count == 1
        # All three callers see the new token (either freshly
        # retrieved or read from the now-updated store).
        assert all(r == new_token for r in results)


# ---------------------------------------------------------------------------
# Pytest config — pytest-asyncio mode is set per-test via marker.
# ---------------------------------------------------------------------------
