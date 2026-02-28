"""
Native OS file dialog for PDF selection.

Launches the platform's native file picker (macOS: NSOpenPanel via osascript,
Linux: zenity/kdialog, Windows: PowerShell OpenFileDialog) in a background
thread so Textual's event loop stays responsive.

Falls back to None when no GUI is available (SSH, headless).
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def _has_gui() -> bool:
    """Detect whether a GUI display is available."""
    if sys.platform == "darwin":
        # macOS: GUI is available unless running over SSH without display forwarding.
        return "SSH_CONNECTION" not in os.environ or "DISPLAY" in os.environ
    elif sys.platform == "win32":
        return True
    else:
        # Linux/BSD: Need X11 or Wayland.
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _linux_file_dialog() -> subprocess.CompletedProcess | None:
    """Try zenity, then kdialog, on Linux. Returns CompletedProcess or None."""
    # Try zenity (GTK)
    try:
        return subprocess.run(
            [
                "zenity",
                "--file-selection",
                "--title=Select a PDF file",
                "--file-filter=PDF files (*.pdf)|*.pdf",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        pass

    # Try kdialog (KDE)
    try:
        return subprocess.run(
            [
                "kdialog",
                "--getopenfilename",
                ".",
                "PDF files (*.pdf)",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        pass

    return None


def _pick_pdf_subprocess() -> Path | None:
    """Run the native file dialog. BLOCKS until user picks or cancels.

    Returns a Path on success, None on cancel or error.
    Must be called from a non-main thread (via asyncio.to_thread).
    """
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose file of type {"com.adobe.pdf"} '
                    'with prompt "Select a PDF file")',
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
        elif sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.OpenFileDialog; "
                "$f.Filter = 'PDF files (*.pdf)|*.pdf'; "
                "$f.Title = 'Select a PDF file'; "
                "if ($f.ShowDialog() -eq 'OK') { $f.FileName }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=300,
            )
        else:
            result = _linux_file_dialog()
            if result is None:
                return None

        if result.returncode != 0:
            return None

        path_str = result.stdout.strip()
        if not path_str:
            return None

        path = Path(path_str)
        if path.is_file() and path.suffix.lower() == ".pdf":
            return path

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


async def pick_pdf_file() -> Path | None:
    """Open a native OS file dialog to pick a PDF file.

    Non-blocking: runs the dialog subprocess in a background thread via
    asyncio.to_thread(), so the calling event loop stays responsive.

    Returns:
        Path to the selected PDF, or None if the user cancelled,
        no GUI is available, or the dialog command was not found.
    """
    if not _has_gui():
        return None

    return await asyncio.to_thread(_pick_pdf_subprocess)
