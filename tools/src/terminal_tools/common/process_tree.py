"""Spawn and clean up only the process tree owned by a terminal command."""

from __future__ import annotations

import os
import signal
import subprocess


def spawn_process(*args, **kwargs) -> subprocess.Popen:
    if os.name != "nt":
        kwargs["start_new_session"] = True
        proc = subprocess.Popen(*args, **kwargs)
        proc._terminal_group = proc.pid
        return proc

    from terminal_tools.common.windows_job import WindowsJob

    job = WindowsJob()
    proc = None
    try:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x4  # CREATE_SUSPENDED
        proc = subprocess.Popen(*args, **kwargs)
        job.assign_and_resume(proc)
        proc._terminal_job = job
        return proc
    except BaseException:
        if proc is not None:
            proc.kill()
            proc.wait()
        job.close()
        raise


def signal_process_tree(proc: subprocess.Popen, signum: int) -> None:
    if os.name == "nt":
        job = getattr(proc, "_terminal_job", None)
        if job is not None and signum == signal.SIGTERM:
            job.terminate()
        else:
            proc.send_signal(signum)
    else:
        group = getattr(proc, "_terminal_group", None)
        if group is not None:
            try:
                os.killpg(group, signum)
            except ProcessLookupError:
                pass
        else:
            proc.send_signal(signum)


def close_process_tree(proc: subprocess.Popen) -> None:
    """Release ownership and stop descendants left behind by an exited shell."""
    if os.name == "nt":
        job = getattr(proc, "_terminal_job", None)
        if job is not None:
            job.close()
    else:
        group = getattr(proc, "_terminal_group", None)
        if group is not None:
            # Cleanup can be reached by both cancellation and the exit watcher.
            # Retire the group ID so a later cleanup cannot signal a reused ID.
            proc._terminal_group = None
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def terminate_process_tree(proc: subprocess.Popen, grace_sec: float = 2.0) -> None:
    signal_process_tree(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
        else:
            signal_process_tree(proc, signal.SIGKILL)
        proc.wait()
    finally:
        close_process_tree(proc)
