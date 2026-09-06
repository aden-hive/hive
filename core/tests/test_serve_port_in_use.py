"""Tests for the busy-port diagnostic in `hive serve` / `hive open`."""

import argparse
import asyncio
import atexit
import errno
import socket

import pytest
from aiohttp import web

from framework.loader import cli


def _occupied_port() -> tuple[socket.socket, int]:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    return holder, holder.getsockname()[1]


async def _start_on(host: str, port: int) -> None:
    runner = web.AppRunner(web.Application(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await cli.start_site_or_raise_port_in_use(site, runner, host, port)
    finally:
        await runner.cleanup()


def test_binding_a_busy_port_raises_a_readable_error_instead_of_oserror():
    holder, port = _occupied_port()
    try:
        with pytest.raises(cli.PortAlreadyInUseError) as raised:
            asyncio.run(_start_on("127.0.0.1", port))
    finally:
        holder.close()

    message = str(raised.value)
    assert str(port) in message
    assert "already in use" in message.lower()
    assert "--port" in message
    assert f"http://127.0.0.1:{port}" in message


def test_other_bind_errors_are_not_swallowed():
    class FailingSite:
        async def start(self) -> None:
            raise OSError(errno.EACCES, "permission denied")

    class NoopRunner:
        async def cleanup(self) -> None:
            return None

    with pytest.raises(OSError) as raised:
        asyncio.run(cli.start_site_or_raise_port_in_use(FailingSite(), NoopRunner(), "127.0.0.1", 8787))

    assert raised.value.errno == errno.EACCES
    assert not isinstance(raised.value, cli.PortAlreadyInUseError)


def test_the_runner_is_cleaned_up_when_the_port_is_busy():
    cleaned: list[bool] = []

    class FailingSite:
        async def start(self) -> None:
            raise OSError(errno.EADDRINUSE, "address already in use")

    class RecordingRunner:
        async def cleanup(self) -> None:
            cleaned.append(True)

    with pytest.raises(cli.PortAlreadyInUseError):
        asyncio.run(cli.start_site_or_raise_port_in_use(FailingSite(), RecordingRunner(), "127.0.0.1", 8787))

    assert cleaned == [True]


def test_cmd_serve_exits_non_zero_and_prints_no_traceback(monkeypatch, capsys):
    monkeypatch.setattr("framework.server.app.create_app", lambda **kwargs: web.Application())
    monkeypatch.setattr(atexit, "register", lambda func: func)

    def fake_run(coro):
        coro.close()
        raise cli.PortAlreadyInUseError("127.0.0.1", 8787)

    monkeypatch.setattr(asyncio, "run", fake_run)
    args = argparse.Namespace(host="127.0.0.1", port=8787, model=None, debug=False, colony=[])

    assert cli.cmd_serve(args) == 1

    out = capsys.readouterr().out
    assert "8787" in out
    assert "already in use" in out.lower()
    assert "Traceback" not in out
