"""Tests for frontend build fallback in the runner CLI."""

import subprocess

from framework.loader import cli as runner_cli


def _write_frontend_tree(tmp_path, *, with_dist: bool = False):
    frontend_dir = tmp_path / "core" / "frontend"
    (frontend_dir / "src").mkdir(parents=True)
    (frontend_dir / "package.json").write_text("{}", encoding="utf-8")
    (frontend_dir / "src" / "main.tsx").write_text("console.log('hi')", encoding="utf-8")
    if with_dist:
        (frontend_dir / "dist").mkdir()
        (frontend_dir / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return frontend_dir


def test_build_frontend_handles_text_calledprocesserror(monkeypatch, tmp_path, capsys):
    _write_frontend_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            cmd,
            output="npm output",
            stderr="vite config failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert runner_cli._build_frontend() is False

    output = capsys.readouterr().out
    assert "Frontend build failed while running" in output
    assert "vite config failed" in output


def test_build_frontend_cleans_cache_and_uses_windows_npm_cmd(monkeypatch, tmp_path):
    frontend_dir = _write_frontend_tree(tmp_path)
    cache_file = frontend_dir / "tsconfig.app.tsbuildinfo"
    cache_file.write_text("stale", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_cli.sys, "platform", "win32")

    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert runner_cli._build_frontend() is True
    assert not cache_file.exists()
    assert commands == [
        ["npm.cmd", "install", "--no-fund", "--no-audit"],
        ["npm.cmd", "run", "build"],
    ]
