"""Hard-block terminal commands that kill or launch the user's browser.

Unlike ``destructive_warning`` (advisory — the command still runs), a
guard hit BLOCKS execution before spawn.

Born from the 2026-06-11 incident: workers whose browser TOOLS timed out
— a runtime transport wedge, not a browser problem — ran
``pkill -9 -f chrome`` and ``kill $(ps aux | grep -i chrome ...)``,
killing the user's personal Chrome (every profile, every window) and all
other agents' sessions, then relaunched it on wrong profiles
(``google-chrome --profile-directory=Default``). The browser bridge
attaches to the USER'S running Chrome via an extension: there is nothing
for an agent to "start", and no situation where killing the browser (or
the Hive bridge/gcu runtime) helps.

Reading process info is fine — ``ps aux | grep chrome``, ``pgrep``,
``which google-chrome`` all pass. Only the kill/launch verbs are blocked.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Process names whose kill/launch is never an agent's job. Includes the
# Hive runtime's own browser plumbing (bridge_host / gcu) — killing those
# breaks every other worker's tools just as thoroughly.
_PROTECTED = r"(?:google[-_]?chrome\S*|chromium(?:-browser)?|chrome\S*|crashpad\S*|msedge\S*|brave\S*|electron\S*|bridge_host|gcu\.\w+)"

# Browser binaries an agent must not exec. Matched only in COMMAND
# position (start of string / after ; & | / after a launch wrapper), so
# `which google-chrome` or `echo chrome` pass.
_BROWSER_BIN = r"(?:[\w./-]*/)?(?:google-chrome(?:-stable|-beta|-unstable)?|chromium(?:-browser)?|chrome)"

_KILL_VERB = r"(?:pkill|killall|kill)"

_BLOCK_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"\b(?:pkill|killall)\b[^\n;|&]*{_PROTECTED}", re.IGNORECASE),
        "kills browser/runtime processes by name",
    ),
    (
        # kill fed by a command substitution that greps for a protected
        # process: kill $(ps aux | grep -i chrome | awk ...)
        re.compile(rf"\b{_KILL_VERB}\b[^\n]*\$\([^)]*grep[^)]*{_PROTECTED}", re.IGNORECASE),
        "kills browser/runtime processes via a ps/grep pipeline",
    ),
    (
        # ...or the xargs spelling: ps aux | grep chrome | ... | xargs kill
        re.compile(rf"grep\b[^\n]*{_PROTECTED}[^\n]*\|\s*(?:xargs\s+)?{_KILL_VERB}\b", re.IGNORECASE),
        "kills browser/runtime processes via a ps/grep pipeline",
    ),
    (
        # Launching a browser binary directly (incl. nohup/setsid/& forms,
        # --profile-directory / --remote-debugging-port / --user-data-dir).
        re.compile(
            rf"(?:^|[;&|]\s*|\b(?:nohup|setsid|exec|env)\s+){_BROWSER_BIN}(?:\s|$)",
            re.IGNORECASE,
        ),
        "launches a browser process",
    ),
    # ── Windows spellings (PowerShell / cmd) ──────────────────────────────
    # The bash patterns above don't catch the Windows equivalents, but on a
    # Windows host the resolved shell may be PowerShell or cmd — so guard the
    # native kill/launch verbs too, or the browser-protection stance has a
    # platform-shaped hole.
    (
        # PowerShell: Stop-Process -Name chrome  /  Get-Process chrome | Stop-Process
        re.compile(rf"\bstop-process\b[^\n]*{_PROTECTED}", re.IGNORECASE),
        "kills browser/runtime processes (PowerShell Stop-Process)",
    ),
    (
        re.compile(rf"\bget-process\b[^\n]*{_PROTECTED}[^\n]*\|\s*(?:[^|\n]*\|\s*)?stop-process\b", re.IGNORECASE),
        "kills browser/runtime processes (PowerShell Get-Process | Stop-Process)",
    ),
    (
        # cmd / Windows: taskkill /IM chrome.exe  (or /F /IM ...)
        re.compile(rf"\btaskkill\b[^\n]*{_PROTECTED}", re.IGNORECASE),
        "kills browser/runtime processes (taskkill)",
    ),
    (
        # PowerShell Start-Process / cmd `start` launching a browser binary
        # (bare `chrome`, quoted `"chrome.exe"`, or a full path all match).
        re.compile(rf"\b(?:start-process|start)\b[^\n;|&]*{_BROWSER_BIN}\b", re.IGNORECASE),
        "launches a browser process",
    ),
)

BLOCK_MESSAGE = (
    "BLOCKED: this command {reason}. The Hive runtime and the user own the "
    "browser's lifecycle — the bridge attaches to the user's ALREADY-RUNNING "
    "Chrome via an extension, so killing or launching browser processes "
    "destroys the user's session and every other agent's work, and there is "
    "nothing for an agent to 'start'. If `hive-browser` commands are timing out "
    "or erroring, that is a transport issue the runtime recovers from "
    "automatically: wait ~30s, retry once, then report_to_parent and move on. "
    "Allowed cleanup is limited to your own tabs via `hive-browser tab close`."
)


def check_command(command: str | Sequence[str]) -> str | None:
    """Return a block message if *command* must not run, else None.

    Accepts both shell strings and argv lists (joined for matching, same
    convention as destructive_warning.get_warning).
    """
    if isinstance(command, (list, tuple)):
        text = " ".join(str(c) for c in command)
    else:
        text = str(command)

    for pattern, reason in _BLOCK_PATTERNS:
        if pattern.search(text):
            return BLOCK_MESSAGE.format(reason=reason)
    return None


__all__ = ["check_command", "BLOCK_MESSAGE"]
