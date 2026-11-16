"""Search dependency discovery and installation, without network or package mutations."""

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from terminal_tools.common import ripgrep


@pytest.fixture
def isolated_discovery(monkeypatch, tmp_path):
    monkeypatch.delenv("HIVE_RIPGREP_PATH", raising=False)
    monkeypatch.setattr(ripgrep.shutil, "which", lambda *args, **kwargs: None)
    monkeypatch.setattr(ripgrep, "_windows_registry_paths", lambda: [])
    monkeypatch.setattr(ripgrep, "_POSIX_PATHS", ())
    monkeypatch.setattr(ripgrep.Path, "home", lambda: tmp_path)
    for name in ("CARGO_HOME", "SCOOP", "SCOOP_GLOBAL", "LOCALAPPDATA", "ProgramFiles", "ChocolateyInstall"):
        monkeypatch.delenv(name, raising=False)
    cached_probe = ripgrep._probe_version
    cached_probe.cache_clear()
    yield
    cached_probe.cache_clear()


def _fake_binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake executable")
    path.chmod(0o755)
    return str(path)


@pytest.mark.parametrize("location", ["cargo", "scoop", "winget", "registry"])
def test_windows_discovery_without_current_path(isolated_discovery, monkeypatch, tmp_path, location):
    monkeypatch.setattr(ripgrep, "_IS_WINDOWS", True)
    directories = {
        "cargo": tmp_path / ".cargo" / "bin",
        "scoop": tmp_path / "scoop" / "shims",
        "winget": tmp_path / "App Data" / "Microsoft" / "WinGet" / "Links",
        "registry": tmp_path / "Custom Install" / "bin",
    }
    target = _fake_binary(directories[location] / "rg.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "App Data"))
    monkeypatch.setattr(ripgrep, "_windows_registry_paths", lambda: [str(directories["registry"])])
    monkeypatch.setattr(ripgrep, "_probe_version", lambda *args: "ripgrep test")
    assert ripgrep.resolve_ripgrep() == target


def test_posix_absolute_location_when_path_is_stripped(isolated_discovery, monkeypatch, tmp_path):
    monkeypatch.setattr(ripgrep, "_IS_WINDOWS", False)
    target = _fake_binary(tmp_path / "usr" / "bin" / "rg")
    monkeypatch.setattr(ripgrep, "_POSIX_PATHS", (target,))
    monkeypatch.setattr(ripgrep, "_probe_version", lambda *args: "ripgrep test")
    assert ripgrep.resolve_ripgrep() == target


def test_broken_path_entry_does_not_hide_a_working_install(isolated_discovery, monkeypatch, tmp_path):
    monkeypatch.setattr(ripgrep, "_IS_WINDOWS", False)
    broken = _fake_binary(tmp_path / "broken" / "rg")
    working = _fake_binary(tmp_path / "working" / "rg")
    monkeypatch.setattr(ripgrep.shutil, "which", lambda *args: broken)
    monkeypatch.setattr(ripgrep, "_POSIX_PATHS", (working,))
    monkeypatch.setattr(ripgrep, "_probe_version", lambda path, *args: "ripgrep test" if path == working else None)
    assert ripgrep.resolve_ripgrep() == working


@pytest.mark.parametrize("override", ["relative/rg.exe", "missing"])
def test_invalid_override_does_not_silently_select_another_rg(isolated_discovery, monkeypatch, tmp_path, override):
    alternate = _fake_binary(tmp_path / "rg.exe")
    monkeypatch.setattr(ripgrep.shutil, "which", lambda *args, **kwargs: alternate)
    monkeypatch.setenv("HIVE_RIPGREP_PATH", str(tmp_path / "missing.exe") if override == "missing" else override)
    assert ripgrep.resolve_ripgrep() is None
    assert ripgrep.ripgrep_status()["code"] == "ripgrep_required"


@pytest.mark.parametrize("failure", ["bad_output", "nonzero", "timeout", "os_error"])
def test_discovery_rejects_unusable_binary(isolated_discovery, monkeypatch, tmp_path, failure):
    target = _fake_binary(tmp_path / "rg.exe")
    monkeypatch.setenv("HIVE_RIPGREP_PATH", target)

    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 2)
        if failure == "os_error":
            raise OSError("cannot execute")
        return subprocess.CompletedProcess(
            argv, 1 if failure == "nonzero" else 0, b"wrong program\n" if failure == "bad_output" else b"ripgrep test\n", b""
        )

    monkeypatch.setattr(ripgrep.subprocess, "run", run)
    assert ripgrep.resolve_ripgrep() is None


def test_version_cache_invalidates_when_binary_changes(isolated_discovery, monkeypatch, tmp_path):
    target = _fake_binary(tmp_path / "rg.exe")
    monkeypatch.setenv("HIVE_RIPGREP_PATH", target)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 2
        return subprocess.CompletedProcess(argv, 0, b"ripgrep test\n", b"")

    monkeypatch.setattr(ripgrep.subprocess, "run", run)
    assert ripgrep.ripgrep_status()["available"]
    assert ripgrep.resolve_ripgrep() == target
    assert len(calls) == 1
    Path(target).write_bytes(b"replacement executable with a different size")
    assert ripgrep.resolve_ripgrep() == target
    assert len(calls) == 2


@pytest.mark.skipif(not ripgrep.resolve_ripgrep(), reason="ripgrep not installed")
def test_real_rg_with_explicit_path_and_empty_path(monkeypatch):
    target = ripgrep.resolve_ripgrep()
    monkeypatch.setenv("HIVE_RIPGREP_PATH", target)
    monkeypatch.setenv("PATH", "")
    status = ripgrep.ripgrep_status()
    assert status["available"]
    assert Path(status["path"]).samefile(target)
    assert status["version"].startswith("ripgrep ")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installation discovery")
def test_native_search_without_path_or_override(monkeypatch, tmp_path, mcp):
    from terminal_tools.search.tools import register_search_tools

    monkeypatch.delenv("HIVE_RIPGREP_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    if not ripgrep.resolve_ripgrep():
        pytest.skip("No independent Windows ripgrep installation")
    root = tmp_path / "中文 work"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".gitignore").write_text("ignored.txt\n")
    (root / "ignored.txt").write_text("needle\n")
    (root / "visible.txt").write_text("before\nneedle\nafter\n")
    register_search_tools(mcp)
    result = mcp._tool_manager._tools["terminal_rg"].fn(pattern="needle", path=str(root), context=1)
    assert "fallback" not in result
    assert result["total"] == 1
    assert [(entry["line"], entry["text"]) for entry in result["context"]] == [(1, "before"), (3, "after")]
    files = mcp._tool_manager._tools["terminal_glob"].fn(pattern="*.txt", path=str(root))
    assert "fallback" not in files
    assert [Path(path).name for path in files["paths"]] == ["visible.txt"]


@pytest.fixture
def installer(monkeypatch):
    monkeypatch.setattr(sys, "path", sys.path.copy())
    script = Path(__file__).resolve().parents[2] / "scripts" / "ensure_ripgrep.py"
    spec = importlib.util.spec_from_file_location("ensure_ripgrep", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("HIVE_RIPGREP_PATH", raising=False)
    return module


def test_installer_never_updates_an_existing_rg(installer, monkeypatch):
    monkeypatch.setattr(installer, "ripgrep_status", lambda: {"available": True, "path": "/rg", "version": "ripgrep test"})
    monkeypatch.setattr(installer, "install_command", lambda: pytest.fail("Must not install or update an available rg"))
    assert installer.main(["--install"]) == 0


@pytest.mark.parametrize("available_after", [False, True])
def test_installer_rechecks_executable_after_package_manager(installer, monkeypatch, available_after):
    missing = {"available": False, "hint": "fix rg"}
    installed = {"available": True, "path": "/new/rg", "version": "ripgrep test"}
    states = iter([missing, installed if available_after else missing])
    monkeypatch.setattr(installer, "ripgrep_status", lambda: next(states))
    monkeypatch.setattr(installer, "install_command", lambda: ["installer", "ripgrep"])
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    assert installer.main(["--install"]) == (0 if available_after else 1)


def test_check_only_does_not_install(installer, monkeypatch):
    monkeypatch.setattr(installer, "ripgrep_status", lambda: {"available": False, "hint": "fix rg"})
    monkeypatch.setattr(installer, "install_command", lambda: pytest.fail("Check mode must not install"))
    assert installer.main([]) == 1


@pytest.mark.parametrize("failure", ["timeout", "os_error", "nonzero", "no_manager"])
def test_failed_install_returns_actionable_error(installer, monkeypatch, capsys, failure):
    monkeypatch.setattr(installer, "ripgrep_status", lambda: {"available": False, "hint": "run quickstart or set HIVE_RIPGREP_PATH"})
    monkeypatch.setattr(installer, "install_command", lambda: None if failure == "no_manager" else ["installer", "ripgrep"])

    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 300)
        if failure == "os_error":
            raise OSError("installer failed")
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main(["--install"]) == 1
    assert "HIVE_RIPGREP_PATH" in capsys.readouterr().err


def test_invalid_override_does_not_trigger_package_install(installer, monkeypatch):
    monkeypatch.setenv("HIVE_RIPGREP_PATH", "/missing/rg")
    monkeypatch.setattr(installer, "ripgrep_status", lambda: {"available": False, "hint": "fix override"})
    monkeypatch.setattr(installer, "install_command", lambda: pytest.fail("An invalid override needs configuration repair"))
    assert installer.main(["--install"]) == 1


def test_windows_install_uses_exact_user_scoped_package(installer, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.shutil, "which", lambda program: "winget.exe" if program == "winget" else None)
    command = installer.install_command()
    assert command[command.index("--id") + 1] == "BurntSushi.ripgrep.MSVC"
    assert command[command.index("--scope") + 1] == "user"
    assert "--exact" in command and "--disable-interactivity" in command


@pytest.mark.parametrize("root", [False, True])
def test_linux_install_respects_privilege_requirements(installer, monkeypatch, root):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0 if root else 1000, raising=False)
    monkeypatch.setattr(installer.shutil, "which", lambda program: f"/usr/bin/{program}" if program in {"apt-get", "sudo"} else None)
    command = installer.install_command()
    assert command == ([] if root else ["/usr/bin/sudo"]) + ["/usr/bin/apt-get", "install", "-y", "ripgrep"]


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_server_startup_reports_search_readiness(monkeypatch, caplog, available):
    from terminal_tools import server

    status = {"available": True, "path": "/rg", "version": "ripgrep test"} if available else {"available": False, "hint": "run quickstart"}
    monkeypatch.delenv("HIVE_DESKTOP_PARENT_PID", raising=False)
    monkeypatch.setattr(server, "ripgrep_status", lambda: status)
    with caplog.at_level(logging.INFO, logger=server.__name__):
        async with server._lifespan(server.mcp):
            assert ("Search ready" if available else "Search dependency missing") in caplog.text
