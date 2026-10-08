"""Own a Windows process tree using a kill-on-close job object.

The process starts suspended so descendants cannot escape before assignment.
Toolhelp retrieves its initial thread, whose handle Popen otherwise closes.
See https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes as W


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", W.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", W.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", W.DWORD),
        ("SchedulingClass", W.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        (name, kind)
        for name, kind in (
            ("dwSize", W.DWORD),
            ("cntUsage", W.DWORD),
            ("th32ThreadID", W.DWORD),
            ("th32OwnerProcessID", W.DWORD),
            ("tpBasePri", W.LONG),
            ("tpDeltaPri", W.LONG),
            ("dwFlags", W.DWORD),
        )
    ]


class WindowsJob:
    def __init__(self):
        self._lock = threading.Lock()
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
            "SetInformationJobObject": ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
            "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
            "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
            "CloseHandle": ([W.HANDLE], W.BOOL),
            "CreateToolhelp32Snapshot": ([W.DWORD, W.DWORD], W.HANDLE),
            "Thread32First": ([W.HANDLE, ctypes.POINTER(_ThreadEntry)], W.BOOL),
            "Thread32Next": ([W.HANDLE, ctypes.POINTER(_ThreadEntry)], W.BOOL),
            "OpenThread": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "ResumeThread": ([W.HANDLE], W.DWORD),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self._api, name)
            fn.argtypes, fn.restype = args, result
        self._handle = self._api.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self._api.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign_and_resume(self, proc) -> None:
        if not self._api.AssignProcessToJobObject(self._handle, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        snapshot = self._api.CreateToolhelp32Snapshot(0x4, 0)  # SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self._api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == proc.pid:
                    thread = self._api.OpenThread(0x2, False, entry.th32ThreadID)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self._api.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        return
                    finally:
                        self._api.CloseHandle(thread)
                found = self._api.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Cannot locate the suspended terminal process thread")
        finally:
            self._api.CloseHandle(snapshot)

    def terminate(self) -> None:
        with self._lock:
            if self._handle and not self._api.TerminateJobObject(self._handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._api.CloseHandle(self._handle)
                self._handle = None
