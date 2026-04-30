"""Background job management for shell-tools."""

from shell_tools.jobs.manager import JobManager, JobRecord, get_manager
from shell_tools.jobs.tools import register_job_tools

__all__ = ["JobManager", "JobRecord", "get_manager", "register_job_tools"]
