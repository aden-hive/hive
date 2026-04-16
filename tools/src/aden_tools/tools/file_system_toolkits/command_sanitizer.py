"""Command sanitization to prevent shell injection attacks.

Validates commands against a blocklist of dangerous patterns before they
are passed to the shell. This prevents prompt injection attacks from
tricking AI agents into running destructive or exfiltration commands on
the host system.

Design: uses a blocklist (not allowlist) so agents can run arbitrary
dev commands (uv, pytest, git, etc.) while blocking known-dangerous ops.
This blocks explicit nested shell executables (bash, sh, pwsh, etc.).
Note: callers use shell=True to support piped/chained commands that
agents legitimately need (cat x | grep y, cmd && cmd2). The shell
operator check in this module catches dangerous chained commands.
"""

import logging
import re

# Structured security logger. Consume via logging.getLogger("aden.security")
# in your log configuration. Fields emitted as `extra` are available in
# structured log formatters (JSON, etc.) for SIEM / SOC2 ingestion.
_security_logger = logging.getLogger("aden.security")

__all__ = ["CommandBlockedError", "validate_command"]


class CommandBlockedError(Exception):
    """Raised when a command is blocked by the safety filter."""

    pass


# ---------------------------------------------------------------------------
# Blocklists
# ---------------------------------------------------------------------------

# Executables / prefixes that are never safe for an AI agent to invoke.
# Matched against each segment of a compound command (split on ; | && ||).
_BLOCKED_EXECUTABLES: list[str] = [
    # Network exfiltration
    "wget",
    "nc",
    "ncat",
    "netcat",
    "nmap",
    "ssh",
    "scp",
    "sftp",
    "ftp",
    "telnet",
    "rsync",
    # Windows network tools
    "invoke-webrequest",
    "invoke-restmethod",
    "iwr",
    "irm",
    "certutil",
    # User / privilege escalation
    "useradd",
    "userdel",
    "usermod",
    "adduser",
    "deluser",
    "passwd",
    "chpasswd",
    "visudo",
    "net",  # net user, net localgroup, etc.
    # System destructive
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init",
    "systemctl",
    "mkfs",
    "fdisk",
    "diskpart",
    "format",  # Windows format
    # Reverse shell / code exec wrappers
    "bash",
    "sh",
    "zsh",
    "dash",
    "csh",
    "ksh",
    "powershell",
    "pwsh",
    "cmd",
    "cmd.exe",
    "wscript",
    "cscript",
    "mshta",
    "regsvr32",
    # Credential / secret access
    "security",  # macOS keychain: security find-generic-password
]

# Patterns matched against the full (joined) command string.
# These catch dangerous flags and argument combos even when the
# executable itself isn't blocked (e.g. python -c '...').
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    # rm with force/recursive flags targeting root or broad paths
    re.compile(r"\brm\s+(-[rRf]+\s+)*(/|~|\.\.|C:\\)", re.IGNORECASE),
    # del /s /q (Windows recursive delete)
    re.compile(r"\bdel\s+.*/[sS]", re.IGNORECASE),
    re.compile(r"\brmdir\s+/[sS]", re.IGNORECASE),
    # dd writing to disks/partitions
    re.compile(r"\bdd\s+.*\bof=\s*/dev/", re.IGNORECASE),
    # chmod 777 / chmod -R 777
    re.compile(r"\bchmod\s+(-R\s+)?(777|666)\b", re.IGNORECASE),
    # sudo — agents should never escalate privileges
    re.compile(r"\bsudo\b", re.IGNORECASE),
    # su — switch user
    re.compile(r"\bsu\s+", re.IGNORECASE),
    # ruby/perl with -e flag (inline code execution)
    re.compile(r"\bruby\s+-e\b", re.IGNORECASE),
    re.compile(r"\bperl\s+-e\b", re.IGNORECASE),
    # powershell encoded commands
    re.compile(r"\bpowershell\b.*-enc", re.IGNORECASE),
    # Reverse shell patterns
    re.compile(r"/dev/tcp/", re.IGNORECASE),
    re.compile(r"\bmkfifo\b", re.IGNORECASE),
    # eval / exec as standalone commands
    re.compile(r"^\s*eval\s+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*exec\s+", re.IGNORECASE | re.MULTILINE),
    # Reading well-known secret files
    re.compile(r"\bcat\s+.*(\.ssh|/etc/shadow|/etc/passwd|credential_key)", re.IGNORECASE),
    re.compile(r"\btype\s+.*credential_key", re.IGNORECASE),
    # Backtick or $() command substitution containing blocked executables
    re.compile(r"\$\(.*\b(wget|nc|ncat)\b.*\)", re.IGNORECASE),
    re.compile(r"`.*\b(wget|nc|ncat)\b.*`", re.IGNORECASE),
    # Environment variable exfiltration via echo/print
    re.compile(r"\becho\s+.*\$\{?.*(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE),
    # >& /dev/tcp (bash reverse shell)
    re.compile(r">&\s*/dev/tcp", re.IGNORECASE),
]

# Shell operators used to split compound commands.
# We check each segment individually against _BLOCKED_EXECUTABLES.
_SHELL_SPLIT_PATTERN = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")


def _normalize_executable_name(token: str) -> str:
    """Normalize executable names for matching (e.g. cmd.exe -> cmd)."""
    normalized = token.lower().strip("\"'")
    normalized = re.split(r"[\\/]", normalized)[-1]
    if normalized.endswith(".exe"):
        return normalized[:-4]
    return normalized


def _extract_executable(segment: str) -> str:
    """Extract the first token (executable) from a command segment.

    Strips environment variable assignments (FOO=bar) from the front.
    """
    segment = segment.strip()
    # Skip env var assignments at the start: VAR=value cmd ...
    tokens = segment.split()
    for token in tokens:
        if "=" in token and not token.startswith("-"):
            continue
        # Return lowercase for case-insensitive matching
        return _normalize_executable_name(token)
    return ""


def validate_command(command: str) -> None:
    """Validate a command string against the safety blocklists.

    Every call is recorded in the ``aden.security`` logger:
    - DEBUG: empty commands (silently passed)
    - INFO:  compound commands containing shell operators (behavioral telemetry)
    - WARNING: any command that is blocked, including the matched pattern

    Args:
        command: The shell command string to validate.

    Raises:
        CommandBlockedError: If the command matches any blocked pattern.
    """
    if not command or not command.strip():
        _security_logger.debug("validate_command: empty or whitespace-only command, skipping")
        return

    stripped = command.strip()
    # Truncate preview to 120 chars so secrets in long commands are not leaked
    # into log files / SIEM streams.
    preview = stripped[:120]

    # Behavioral telemetry: compound commands are not blocked, but their
    # presence is logged so rogue-agent patterns can be detected in aggregate.
    if _SHELL_SPLIT_PATTERN.search(stripped):
        _security_logger.info(
            "compound_command_detected",
            extra={"command_preview": preview},
        )

    # --- Check full-command patterns ---
    for pattern in _BLOCKED_PATTERNS:
        match = pattern.search(stripped)
        if match:
            _security_logger.warning(
                "command_blocked",
                extra={
                    "reason": "pattern_match",
                    "pattern": pattern.pattern,
                    "matched_text": match.group(),
                    "command_preview": preview,
                },
            )
            raise CommandBlockedError(
                f"Command blocked for safety: matched dangerous pattern '{match.group()}'. "
                f"If this is a false positive, please modify the command."
            )

    # --- Check each segment for blocked executables ---
    segments = _SHELL_SPLIT_PATTERN.split(stripped)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        executable = _extract_executable(segment)
        # Check exact match and prefix-before-dot (e.g. mkfs.ext4 -> mkfs)
        names_to_check = {executable}
        if "." in executable:
            names_to_check.add(executable.split(".")[0])
        if names_to_check & set(_BLOCKED_EXECUTABLES):
            matched = (names_to_check & set(_BLOCKED_EXECUTABLES)).pop()
            _security_logger.warning(
                "command_blocked",
                extra={
                    "reason": "blocked_executable",
                    "executable": matched,
                    "command_preview": preview,
                },
            )
            raise CommandBlockedError(
                f"Command blocked for safety: '{matched}' is not allowed. "
                f"Blocked categories: network tools, privilege escalation, "
                f"system destructive commands, shell interpreters."
            )
