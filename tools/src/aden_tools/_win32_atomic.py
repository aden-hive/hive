"""Windows atomic file replacement with DACL preservation.

Uses ReplaceFileW for atomic replacement, then SetFileSecurityW to
restore the exact original DACL.  ReplaceFileW merges ACEs from the
temp file, which can duplicate inherited entries.  SetFileSecurityW
restores the security descriptor as-is without re-evaluating
inheritance (unlike SetNamedSecurityInfoW).

On non-NTFS volumes (e.g. FAT32), DACL snapshot/restore is skipped
gracefully and only the atomic replacement is performed.
"""

import ctypes
import ctypes.wintypes

_DACL_SECURITY_INFORMATION = 0x00000004
_REPLACEFILE_IGNORE_MERGE_ERRORS = 0x00000002

_advapi32 = None
_kernel32 = None

if hasattr(ctypes, "windll"):
    _advapi32 = ctypes.windll.advapi32
    _kernel32 = ctypes.windll.kernel32

    _advapi32.GetFileSecurityW.argtypes = [
        ctypes.wintypes.LPCWSTR,  # lpFileName
        ctypes.wintypes.DWORD,  # RequestedInformation
        ctypes.c_void_p,  # pSecurityDescriptor
        ctypes.wintypes.DWORD,  # nLength
        ctypes.POINTER(ctypes.wintypes.DWORD),  # lpnLengthNeeded
    ]
    _advapi32.GetFileSecurityW.restype = ctypes.wintypes.BOOL

    _advapi32.SetFileSecurityW.argtypes = [
        ctypes.wintypes.LPCWSTR,  # lpFileName
        ctypes.wintypes.DWORD,  # SecurityInformation
        ctypes.c_void_p,  # pSecurityDescriptor
    ]
    _advapi32.SetFileSecurityW.restype = ctypes.wintypes.BOOL

    _kernel32.ReplaceFileW.argtypes = [
        ctypes.wintypes.LPCWSTR,  # lpReplacedFileName
        ctypes.wintypes.LPCWSTR,  # lpReplacementFileName
        ctypes.wintypes.LPCWSTR,  # lpBackupFileName
        ctypes.wintypes.DWORD,  # dwReplaceFlags
        ctypes.c_void_p,  # lpExclude (reserved)
        ctypes.c_void_p,  # lpReserved
    ]
    _kernel32.ReplaceFileW.restype = ctypes.wintypes.BOOL


def snapshot_dacl(path: str) -> ctypes.Array | None:
    """Save a file's DACL as raw bytes.  Returns None on non-NTFS."""
    if _advapi32 is None:
        return None

    needed = ctypes.wintypes.DWORD()
    _advapi32.GetFileSecurityW(
        path,
        _DACL_SECURITY_INFORMATION,
        None,
        0,
        ctypes.byref(needed),
    )
    if needed.value == 0:
        return None
    sd_buf = ctypes.create_string_buffer(needed.value)
    if not _advapi32.GetFileSecurityW(
        path,
        _DACL_SECURITY_INFORMATION,
        sd_buf,
        needed.value,
        ctypes.byref(needed),
    ):
        return None
    return sd_buf


def atomic_replace(target: str, replacement: str) -> None:
    """Atomically replace *target* with *replacement*, preserving the DACL.

    Uses ReplaceFileW for the atomic swap, then restores the original
    DACL via SetFileSecurityW (best-effort).
    """
    if _kernel32 is None or _advapi32 is None:
        raise OSError("atomic_replace is only available on Windows")

    sd_buf = snapshot_dacl(target)

    if not _kernel32.ReplaceFileW(
        target,
        replacement,
        None,
        _REPLACEFILE_IGNORE_MERGE_ERRORS,
        None,
        None,
    ):
        raise ctypes.WinError()

    # Best-effort: content is already saved, don't fail the whole edit
    # over a DACL restore failure.
    if sd_buf is not None:
        _advapi32.SetFileSecurityW(
            target,
            _DACL_SECURITY_INFORMATION,
            sd_buf,
        )
