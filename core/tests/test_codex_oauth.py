import io
import threading
import time

import codex_oauth


def _redirect_url(state: str, code: str) -> str:
    return f"{codex_oauth.REDIRECT_URI}?code={code}&state={state}"


def test_wait_for_code_accepts_valid_manual_input_after_invalid_entry():
    state = "expected-state"
    stdin = io.StringIO(f"not a valid code\n{_redirect_url(state, 'manual-code')}\n")

    code = codex_oauth.wait_for_code_from_callback_or_stdin(
        state,
        [None],
        threading.Event(),
        timeout_secs=0.5,
        poll_interval=0.01,
        stdin=stdin,
    )

    assert code == "manual-code"


def test_wait_for_code_returns_callback_when_stdin_reader_fails():
    class BrokenStdin:
        def readline(self) -> str:
            raise OSError("stdin unavailable")

    state = "expected-state"
    callback_result: list[str | None] = [None]
    callback_done = threading.Event()

    def resolve_callback() -> None:
        time.sleep(0.02)
        callback_result[0] = "callback-code"
        callback_done.set()

    threading.Thread(target=resolve_callback, daemon=True).start()

    code = codex_oauth.wait_for_code_from_callback_or_stdin(
        state,
        callback_result,
        callback_done,
        timeout_secs=0.5,
        poll_interval=0.01,
        stdin=BrokenStdin(),
    )

    assert code == "callback-code"


def test_open_browser_uses_windows_startfile(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(codex_oauth.platform, "system", lambda: "Windows")
    monkeypatch.setattr(codex_oauth.os, "startfile", calls.append, raising=False)

    def fail_popen(*args, **kwargs):
        raise AssertionError("Windows browser launch should not go through cmd /c start")

    monkeypatch.setattr(codex_oauth.subprocess, "Popen", fail_popen)

    assert codex_oauth.open_browser("https://example.com/path?a=1&b=2") is True
    assert calls == ["https://example.com/path?a=1&b=2"]
